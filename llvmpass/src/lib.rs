use std::collections::HashMap;

use llvm_plugin::inkwell::module::Module;
use llvm_plugin::inkwell::values::*;
use llvm_plugin::{
    LlvmModulePass, ModuleAnalysisManager, PassBuilder, PipelineParsing, PreservedAnalyses,
};

// A name and version is required.
#[llvm_plugin::plugin(name = "rainbow", version = "0.1")]
fn plugin_registrar(builder: &mut PassBuilder) {
    // Add a callback to parse a name from the textual representation of the pipeline to be run.
    builder.add_module_pipeline_parsing_callback(|name, manager| {
        if name == "rainbow" {
            // the input pipeline contains the name "custom-pass", so we add our custom pass to the
            // pass manager
            manager.add_pass(RainbowPass);
            //manager.add_pass(GlobalVariablePointerRenamePass);

            // we notify the caller that we were able to parse
            // the given name
            PipelineParsing::Parsed
        } else {
            // in any other cases, we notify the caller that our
            // callback wasn't able to parse the given name
            PipelineParsing::NotParsed
        }
    });
}

fn expect(src: &str, idx: usize, expected: u8) -> Option<usize> {
    if src.as_bytes()[idx] == expected {
        Some(idx + 1)
    } else {
        None
    }
}

fn expect_str(src: &str, idx: usize, expected: &str) -> Option<usize> {
    let mut i = idx;
    for c in expected.chars() {
        i = expect(src, i, c as u8)?
    }
    Some(i)
}

fn read_int(src: &str, idx: usize) -> Option<(usize, i32)> {
    let first_char = src.as_bytes()[idx];
    if first_char < b'0' || first_char > b'9' {
        return None;
    }

    let mut res: i32 = 0;
    let mut i = idx;
    while src.as_bytes()[i] > b'0' && src.as_bytes()[i] < b'9' {
        res *= 10;
        res += (src.as_bytes()[i] - b'0') as i32;
        i += 1;
    }

    Some((i, res))
}

fn read_struct(src: &str, idx_: usize) -> Option<(usize, Vec<String>)> {
    let mut idx = idx_;

    idx = expect_str(src, idx, "{ ")?;
    let start = idx;
    while src.as_bytes()[idx] != b'}' {
        idx += 1;
    }
    let res: Vec<String> = src[start..(idx - 1)]
        .to_string()
        .split(", ")
        .map(|a| a.to_string())
        .collect();
    idx = expect(src, idx, b'}')?;
    Some((idx, res))
}

fn read_and_ignore_struct(src: &str, idx: usize) -> Option<usize> {
    let (res, _) = read_struct(src, idx)?;
    Some(res)
}

#[derive(Debug)]
enum Annotation {
    String(String),
    Location(String, i32),
}

fn ignore_type(src: &str) -> String {
    // convert "<type> <value>" into <value>
    let mut iter = src.split_whitespace();
    iter.next();
    return iter.next().unwrap().to_string();
}

fn get_global_str(module: &mut Module, name: &str) -> String {
    let res = module.get_global(name).unwrap();
    let res = res.get_initializer().unwrap();
    let res = res.into_array_value();
    let res = res.get_string_constant().unwrap().to_string_lossy();
    res.to_string()
}

// llvm-c doesn't expose ConstantArray, so we need to parse the dumped annotations object to get
// global annotations.
fn parse_global_fn_annotations(src: &str, module: &mut Module) -> HashMap<String, Vec<Annotation>> {
    let mut res = HashMap::new();

    let mut idx: usize = 0;
    idx = expect_str(src, idx, "\"[").unwrap();
    let (mut idx, n_entries) = read_int(src, idx).unwrap();
    idx = expect_str(src, idx, " x ").unwrap();
    idx = read_and_ignore_struct(src, idx).unwrap();
    idx = expect_str(src, idx, "] [").unwrap();
    for entry in 0..n_entries {
        idx = read_and_ignore_struct(src, idx).unwrap();
        idx = expect(src, idx, b' ').unwrap();
        let (new_idx, struct_) = read_struct(src, idx).unwrap();
        idx = new_idx;

        // Parse [ptr <function>, ptr <attrs>..., ptr <filename>, i32 <line no>, ptr null]
        assert!(struct_.len() >= 4);
        if struct_.len() == 4 {
            // Only has location annotations, nothing else
            continue;
        }
        let mut annotations = Vec::new();
        let annotations_end = struct_.len() - 3;

        let filename = struct_[annotations_end].clone();
        let lineno = struct_[annotations_end + 1].clone();
        annotations.push(Annotation::Location(
            get_global_str(module, &ignore_type(&filename)[1..]),
            ignore_type(&lineno).parse().unwrap(),
        ));

        for annotation_str in &struct_[1..annotations_end] {
            annotations.push(Annotation::String(get_global_str(
                module,
                &ignore_type(annotation_str)[1..],
            )));
        }
        res.insert(ignore_type(&struct_[0])[1..].to_string(), annotations);

        if entry != (n_entries - 1) {
            idx = expect_str(src, idx, ", ").unwrap();
        }
    }

    expect_str(src, idx, "]\"").unwrap();
    res
}

fn alloca_is_lambda_defn(instr: &InstructionValue) -> bool {
    assert!(instr.get_opcode() == InstructionOpcode::Alloca);
    let str = instr.to_string();
    let mut iter = str.split(" = ").peekable();
    iter.next().unwrap();
    let defn = iter.peek().unwrap();
    let mut iter = defn["alloca ".len()..].split(',').peekable();
    iter.peek().unwrap().starts_with("%class.anon")
}

struct RainbowPass;
impl LlvmModulePass for RainbowPass {
    fn run_pass(&self, module: &mut Module, _manager: &ModuleAnalysisManager) -> PreservedAnalyses {
        let annotations = module.get_global("llvm.global.annotations").unwrap();
        let value = annotations.get_initializer().unwrap();
        let value = value.into_array_value();
        let valstr = value.to_string();
        let glbl_annotations = parse_global_fn_annotations(&valstr, module);
        println!("glbl_annotations={:?}", glbl_annotations);

        let fmain = module.get_function("main").unwrap();
        // How to lookup "main" in annotations?
        // fmain.print_to_stderr();
        for b in fmain.get_basic_block_iter() {
            for instr in b.get_instructions() {
                // println!("  INSTR: {}", instr.to_string());
                match instr.get_opcode() {
                    InstructionOpcode::Alloca => {
                        let b = alloca_is_lambda_defn(&instr);
                        if b {
                            println!("  INSTR: {}", instr.to_string());
                        }
                    }
                    InstructionOpcode::Call => {
                        // if instr is a CALL to llvm.var.annotation.p0.p0 then we need to create a
                        // new annotation, but only if arg0 is of type %class.anon*
                        println!("  INSTR: {}", instr.to_string());
                        let res: Vec<_> = instr.get_operands().collect();
                        println!("         {:?}", res);
                    }
                    // TODO within a lambda things look pretty weird. We need to track which elemnts
                    // on the stack of a lambda have which annotations, and then propogate that to
                    // other functions that might invoke the lambda.
                    _ => {
                        // println!("    type: {:?}", instr.get_opcode());
                    }
                }
            }
        }
        PreservedAnalyses::All
    }
}
