#!/bin/zsh
# Double-click this file in Finder to compile-check the Planner backend.
# It does NOT start the server or touch the database — it only asks the Rust
# compiler whether the code builds, and prints any errors.

cd "$HOME/TCS-Planner/backend" || { echo "Could not find ~/TCS-Planner/backend"; read; exit 1; }

# Belt-and-suspenders: ignore any stray DATABASE_URL from the shell environment
# so it can't collide with the role-planner/rag setup during the check.
unset DATABASE_URL

echo "Checking the Planner backend in: $PWD"
echo "(this can take a minute the first time)"
echo

cargo check

status=$?
echo
if [ $status -eq 0 ]; then
  echo "✅ cargo check passed — the code compiles."
else
  echo "❌ cargo check found errors (scroll up). Copy them and paste them to Claude."
fi
echo
echo "---- Press Return to close this window. ----"
read
