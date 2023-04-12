import os
import sys

from . import rainbow

if "RAINBOW_PROFILE" in os.environ:
    import cProfile

    cProfile.run("rainbow.main()")
    sys.exit(0)
rainbow.main()
