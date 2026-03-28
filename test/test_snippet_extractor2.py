
import os
import sys
from pathlib import Path

# Add the project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from src.utils.snippet_extractor2 import extract_snippet

suspicious_locations = """Bug ID: astropy__astropy-14182
## Suspicious Locations
--- Suspicious Files ---
- astropy/io/ascii/rst.py
- astropy/io/ascii/core.py
- astropy/io/ascii/ui.py
- astropy/table/connect.py
- astropy/io/registry/core.py

--- Related Functions ---
- astropy/io/ascii/rst.py: RST.__init__
- astropy/io/ascii/core.py: _get_writer
- astropy/io/ascii/ui.py: get_writer
- astropy/table/connect.py: TableWrite.__call__
- astropy/io/registry/core.py: UnifiedOutputRegistry.get_writer

--- Edit Locations ---
- File: astropy/io/ascii/core.py | Func: _get_writer | Lines: [1814, 60]"""

# print(suspicious_locations)

margin = 10 # snippet context window
repo_path = "/path/to/spade/data/repos/astropy__astropy"
suspicious_files = [
    "astropy/io/ascii/rst.py",
    "astropy/io/ascii/core.py",
    "astropy/io/ascii/ui.py",
    "astropy/table/connect.py",
    "astropy/io/registry/core.py"
]
related_functions = {
    "astropy/io/ascii/rst.py": ["RST.__init__"],
    "astropy/io/ascii/core.py": ["_get_writer"],
    "astropy/io/ascii/ui.py": ["get_writer"],
    "astropy/table/connect.py": ["TableWrite.__call__"],
    "astropy/io/registry/core.py": ["UnifiedOutputRegistry.get_writer"]
}
edit_locations = {
    "astropy/io/ascii/core.py": {
        "function": "_get_writer",
        "lines": [1814, 60]
    },
}

if repo_path.startswith("/path/to"):
    raise Exception("please specify repo path")

snippet = extract_snippet(repo_path, suspicious_files, related_functions, edit_locations, margin)
print(snippet)

"""
Example output:


### File: astropy/io/ascii/core.py
```python
     50:         return
     51: 
     52:     # Check for N-d columns
     53:     nd_names = [col.info.name for col in table.itercols() if len(col.shape) > max_ndim]
     54:     if nd_names:
     55:         raise ValueError(
     56:             f"column(s) with dimension > {max_ndim} "
     57:             "cannot be be written with this format, try using 'ecsv' "
     58:             "(Enhanced CSV) format"
     59:         )
>>   60: 
     61: 
     62: class CsvWriter:
    ...
    ...
f> 1793: def _get_writer(Writer, fast_writer, **kwargs):
    ...
   1804:     if "fill_values" in kwargs and kwargs["fill_values"] is None:
   1805:         del kwargs["fill_values"]
   1806: 
   1807:     if issubclass(Writer, FastBasic):  # Fast writers handle args separately
   1808:         return Writer(**kwargs)
   1809:     elif fast_writer and f"fast_{Writer._format_name}" in FAST_CLASSES:
   1810:         # Switch to fast writer
   1811:         kwargs["fast_writer"] = fast_writer
   1812:         return FAST_CLASSES[f"fast_{Writer._format_name}"](**kwargs)
   1813: 
>> 1814:     writer_kwargs = {k: v for k, v in kwargs.items() if k not in extra_writer_pars}
   1815:     writer = Writer(**writer_kwargs)
   1816: 
   1817:     if "delimiter" in kwargs:
   1818:         writer.header.splitter.delimiter = kwargs["delimiter"]
   1819:         writer.data.splitter.delimiter = kwargs["delimiter"]
   1820:     if "comment" in kwargs:
   1821:         writer.header.write_comment = kwargs["comment"]
   1822:         writer.data.write_comment = kwargs["comment"]
   1823:     if "quotechar" in kwargs:
   1824:         writer.header.splitter.quotechar = kwargs["quotechar"]
```

### File: astropy/io/ascii/rst.py
```python
f>   35: class RST(FixedWidth):
    ...
    ...
     54: 
     55:     _format_name = "rst"
     56:     _description = "reStructuredText simple table"
     57:     data_class = SimpleRSTData
     58:     header_class = SimpleRSTHeader
     59: 
f>   60:     def __init__(self):
     61:         super().__init__(delimiter_pad=None, bookend=False)
     62: 
     63:     def write(self, lines):
     64:         lines = super().write(lines)
     65:         lines = [lines[1]] + lines + [lines[1]]
     66:         return lines
```

### File: astropy/io/ascii/ui.py
```python
    854:     "comment",
    855:     "quotechar",
    856:     "formats",
    857:     "names",
    858:     "include_names",
    859:     "exclude_names",
    860:     "strip_whitespace",
    861: )
    862: 
    863: 
f>  864: def get_writer(Writer=None, fast_writer=True, **kwargs):
    ...
    897:     if Writer is None:
    898:         Writer = basic.Basic
    899:     if "strip_whitespace" not in kwargs:
    900:         kwargs["strip_whitespace"] = True
    901:     writer = core._get_writer(Writer, fast_writer, **kwargs)
    902: 
    903:     # Handle the corner case of wanting to disable writing table comments for the
    904:     # commented_header format.  This format *requires* a string for `write_comment`
    905:     # because that is used for the header column row, so it is not possible to
    906:     # set the input `comment` to None.  Without adding a new keyword or assuming
    907:     # a default comment character, there is no other option but to tell user to
    908:     # simply remove the meta['comments'].
    909:     if isinstance(
    910:         writer, (basic.CommentedHeader, fastbasic.FastCommentedHeader)
    911:     ) and not isinstance(kwargs.get("comment", ""), str):
    912:         raise ValueError(
    913:             "for the commented_header writer you must supply a string\n"
    914:             "value for the `comment` keyword.  In order to disable writing\n"
    915:             "table comments use `del t.meta['comments']` prior to writing."
    916:         )
    917: 
    918:     return writer
    919: 
    920: 
    921: def write(
    922:     table,
    923:     output=None,
    924:     format=None,
    925:     Writer=None,
    926:     fast_writer=True,
    927:     *,
    928:     overwrite=False,
    929:     **kwargs,
    930: ):
```

### File: astropy/io/registry/core.py
```python
f>  241: class UnifiedOutputRegistry(_UnifiedIORegistryBase):
    ...
    304:             self._writers.pop((data_format, data_class))
    305:         else:
    306:             raise IORegistryError(
    307:                 f"No writer defined for format '{data_format}' and class"
    308:                 f" '{data_class.__name__}'"
    309:             )
    310: 
    311:         if data_class not in self._delayed_docs_classes:
    312:             self._update__doc__(data_class, "write")
    313: 
f>  314:     def get_writer(self, data_format, data_class):
    ...
    330:         writers = [(fmt, cls) for fmt, cls in self._writers if fmt == data_format]
    331:         for writer_format, writer_class in writers:
    332:             if self._is_best_match(data_class, writer_class, writers):
    333:                 return self._writers[(writer_format, writer_class)][0]
    334:         else:
    335:             format_table_str = self._get_format_table_str(data_class, "Write")
    336:             raise IORegistryError(
    337:                 f"No writer defined for format '{data_format}' and class"
    338:                 f" '{data_class.__name__}'.\n\nThe available formats"
    339:                 f" are:\n\n{format_table_str}"
    340:             )
    341: 
    342:     def write(self, data, *args, format=None, **kwargs):
    ...
```

### File: astropy/table/connect.py
```python
f>   83: class TableWrite(registry.UnifiedReadWrite):
    ...
    ...
    122: 
    123:     def __init__(self, instance, cls):
    124:         super().__init__(instance, cls, "write", registry=None)
    125:         # uses default global registry
    126: 
f>  127:     def __call__(self, *args, serialize_method=None, **kwargs):
    128:         instance = self._instance
    129:         with serialize_method_as(instance, serialize_method):
    130:             self.registry.write(instance, *args, **kwargs)
```
"""