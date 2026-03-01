#!/bin/bash

# Define the name of the output zip file
OUTPUT_ZIP="spade_src.zip"

echo "Packaging project into $OUTPUT_ZIP..."

# Remove the old zip file if it exists so we don't zip the zip!
if [ -f "$OUTPUT_ZIP" ]; then
    rm "$OUTPUT_ZIP"
fi

# Run the zip command
# -r means recursive (include all folders)
# -x specifies the patterns to exclude
zip -r "$OUTPUT_ZIP" . \
    -x "*.venv/*" \
    -x "*__pycache__/*" \
    -x "*.git/*" \
    -x "*.DS_Store" \
    -x "*$OUTPUT_ZIP"

echo "Done! Source code is zipped in: $OUTPUT_ZIP"