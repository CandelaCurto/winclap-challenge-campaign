# data/

`campaigns.csv` is the file the pipeline processes. To load new data, replace it with a file of the
same name: pushing it to `main` runs the workflow, which publishes the result to the Sheets. See
[how to update the data](../docs/updating-data.md).

The tests do not use this file: they use a fixed copy of the case CSV in `tests/fixtures/`.
