"""Execute this project's Python notebook cells without opening kernel sockets.

This is an in-process smoke check, not a test of Jupyter kernel startup/transport.
Install requirements-notebook.txt and run from the repository root.
"""
import io
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import nbformat
from IPython.core.interactiveshell import InteractiveShell
from IPython.display import Image, display
from IPython.utils.capture import capture_output


def execute(path):
    path = Path(path).resolve()
    notebook = nbformat.read(path, as_version=4)
    os.chdir(path.parent)
    sys.path.insert(0, str(path.parent))
    shell = InteractiveShell.instance()
    original_show = plt.show

    def capture_figures(*args, **kwargs):
        for number in plt.get_fignums():
            figure = plt.figure(number)
            buffer = io.BytesIO()
            figure.savefig(buffer, format='png', dpi=120, bbox_inches='tight')
            display(Image(data=buffer.getvalue()))
            plt.close(figure)

    plt.show = capture_figures
    try:
        count = 0
        for cell in notebook.cells:
            if cell.cell_type != 'code':
                continue
            count += 1
            with capture_output() as captured:
                result = shell.run_cell(cell.source, store_history=True)
            if result.error_before_exec or result.error_in_exec:
                raise RuntimeError(f'Notebook cell {count} failed') from (
                    result.error_before_exec or result.error_in_exec)
            cell.execution_count = count
            cell.outputs = []
            for name in ('stdout', 'stderr'):
                text = getattr(captured, name)
                if text:
                    cell.outputs.append(nbformat.v4.new_output('stream', name=name, text=text))
            for output in captured.outputs:
                cell.outputs.append(nbformat.v4.new_output(
                    'display_data', data=output.data, metadata=output.metadata))
            print(f'Executed code cell {count}', flush=True)
        notebook.metadata['verification'] = {
            'method': 'Sequential IPython in-process execution; actual captured outputs',
            'limitation': 'Jupyter kernel transport/startup not tested; environment blocks sockets',
        }
        nbformat.validate(notebook)
        nbformat.write(notebook, path)
    finally:
        plt.show = original_show


if __name__ == '__main__':
    execute(sys.argv[1] if len(sys.argv) > 1 else 'AirQuality.ipynb')
