# VHS Tape Configuration for payday-super-checker
# Run `vhs tools/demo.tape` to generate assets/demo.gif

Output assets/demo.gif
Output assets/demo.svg

Set FontSize 14
Set Width 900
Set Height 500
Set Padding 20
Set Theme "Catppuccin Mocha"
Set WindowBar Colorful

Type "payday-super-check examples/sample_payrun_no_transition.csv --as-at 2026-09-10"
Sleep 500ms
Enter

Sleep 3s
