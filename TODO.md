# TODOs

## BUGs

- ~~Invalid Config should raise and let the user know~~ — resolved in step 17 (test_invalid_json_all_files_raises, test_invalid_json_all_files_includes_paths)

## Commits to review/cleanup

### CLI + lib fix

- c32f524 cli: show raw source snippet in statement headings
- 0a0466d Render each pipeline segment's redirection adjacent to its command
- 9b30b89 Split BinaryCmd redirections into per-operand fields
- 2d78a25 Fix dropped redirections in compound commands and pipelines
- 5c6f08a Add delightful CLI for pretty-printing bash inspection
