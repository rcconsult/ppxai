# INERT — never executed in the in-process tier (no shell grant). Present only
# so the loader detects a non-empty scripts/ dir and the server applies the
# allow_skill_scripts gate. Running skill scripts needs the container tier (T9).
echo "this never runs under /task"
