"""Plugins to post process notebooks.

All functions should take (notebook, resources) as input,
and output a (new notebook, resources).
"""
import copy
import functools
import pkg_resources
import re
import textwrap

from nbformat import NotebookNode


ENTRY_POINT_NAME = "nbreg.post_proc"


@functools.lru_cache()
def list_processor_names():
    """List entry point names for  post-processors."""
    return [ep.name for ep in pkg_resources.iter_entry_points(ENTRY_POINT_NAME)]


@functools.lru_cache()
def load_processor(name: str):
    """Get a post-processors for an entry point name."""
    matches = [
        ep
        for ep in pkg_resources.iter_entry_points(ENTRY_POINT_NAME)
        if ep.name == name
    ]
    if not matches:
        raise ValueError(
            "entry point '{}' for group '{}' not found".format(name, ENTRY_POINT_NAME)
        )
    return matches[0].load()


def document_processors():
    """Create formatted string of all preprocessor docstrings."""
    return "\n\n".join(
        [
            "{}:\n{}".format(n, textwrap.indent(load_processor(n).__doc__, "  "))
            for n in list_processor_names()
        ]
    )


def cell_preprocessor(function):
    """Wrap a function to be executed on all cells of a notebook.

    The wrapped function should have these parameters:

    cell : NotebookNode cell
        Notebook cell being processed
    resources : dictionary
        Additional resources used in the conversion process.
    index : int
        Index of the cell being processed
    """

    @functools.wraps(function)
    def wrappedfunc(nb: NotebookNode, resources: dict) -> (NotebookNode, dict):
        new_nb = copy.deepcopy(nb)
        for index, cell in enumerate(new_nb.cells):
            new_nb.cells[index], resources = function(cell, resources, index)
        return new_nb, resources

    return wrappedfunc


RGX_CARRIAGERETURN = re.compile(r".*\r(?=[^\n])")
RGX_BACKSPACE = re.compile(r"[^\n]\b")


@cell_preprocessor
def coalesce_streams(
    cell: NotebookNode, resources: dict, index: int
) -> (NotebookNode, dict):
    """Merge all stream outputs with shared names into single streams.

    This ensure deterministic outputs.

    Adapted from:
    https://github.com/computationalmodelling/nbval/blob/master/nbval/plugin.py

    """

    if "outputs" not in cell:
        return cell, resources

    new_outputs = []
    streams = {}
    for output in cell.outputs:
        if output.output_type == "stream":
            if output.name in streams:
                streams[output.name].text += output.text
            else:
                new_outputs.append(output)
                streams[output.name] = output
        else:
            new_outputs.append(output)

    # process \r and \b characters
    for output in streams.values():
        old = output.text
        while len(output.text) < len(old):
            old = output.text
            # Cancel out anything-but-newline followed by backspace
            output.text = RGX_BACKSPACE.sub("", output.text)
        # Replace all carriage returns not followed by newline
        output.text = RGX_CARRIAGERETURN.sub("", output.text)

    cell.outputs = new_outputs

    return cell, resources


@cell_preprocessor
def blacken_code(
    cell: NotebookNode, resources: dict, index: int
) -> (NotebookNode, dict):
    """Format python source code with black (see https://black.readthedocs.io)."""
    try:
        import black
    except ImportError:
        raise ImportError("black not installed: see https://black.readthedocs.io")

    if cell.get("cell_type", None) != "code":
        return cell, resources

    # TODO use metadata to set target versions
    # i.e. black.FileMode(target_versions, {black.TargetVersion.PY36})
    try:
        cell.source = black.format_str(cell.source, mode=black.FileMode())
    except (SyntaxError, black.InvalidInput):
        pass

    return cell, resources
