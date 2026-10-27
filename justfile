# Test src/pytatr.py against tasks/README.md and README.md
test *args:
    uv run --quiet src/test_pytatr.py {{args}}

#######################################
# Tasks (see tasks/README.md)
#######################################

# List open tasks, e.g. `just tasks --tag bug --lt 50`
[positional-arguments]
tasks *args:
    @uv run --quiet src/pytatr.py ls "$@"

# Task commands: ls, new, find, ref, summary, todo, help (e.g. `just task find 202610`)
[positional-arguments]
task command="help" *args:
    @uv run --quiet src/pytatr.py "$@"
