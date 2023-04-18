[[clang::annotate("DISALLOWED")]] int disallowed() { return 0; }
[[clang::annotate("DISALLOWED")]] int also_disallowed() { return 0; }
int main() { return disallowed(); }
