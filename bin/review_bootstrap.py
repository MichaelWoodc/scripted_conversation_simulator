"""Reload changed review controls and replace displayed widgets in running kernels.
"""
import importlib
from pathlib import Path


def get_review_studio(namespace):
    if namespace.get('cell_studio') is not None:
        return get_cell_studio(namespace)
    modules = []
    stamps = []
    for name in ('answer_tts', 'emphasized_delivery', 'answer_review'):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        version = (path.stat().st_mtime_ns, path.stat().st_size)
        if getattr(module, '_loaded_review_stamp', None) != version:
            importlib.invalidate_caches()
            module = importlib.reload(module)
            module._loaded_review_stamp = version
        modules.append(module)
        stamps.append(version)
    answer_tts, _, answer_review = modules
    stamp = tuple(stamps)
    previous = namespace.get('studio')
    if isinstance(previous, answer_review.AnswerReviewStudio) and getattr(previous, '_review_stamp', None) == stamp:
        return previous
    if previous is not None and any(getattr(e, '_busy', False) for e in getattr(previous, 'editors', {}).values()):
        raise RuntimeError('Wait for the current preview to finish, then run this cell again.')
    output = previous.store.output if previous is not None and hasattr(previous, 'store') else answer_review.REVIEW_OUTPUT
    if previous is not None:
        for old_editor in getattr(previous, 'editors', {}).values():
            previous.store.update_draft(old_editor.answer, old_editor.settings())
    studio = answer_review.AnswerReviewStudio(output=output)
    studio._review_stamp = stamp
    if previous is not None and hasattr(previous, 'editors'):
        studio.engines = dict(getattr(previous, 'engines', {}))
        for engine in studio.engines.values():
            if type(engine).__name__ in ('TTSEngine', 'EmphasizedTTSEngine'):
                # Keep loaded model weights, while removing every old DSP method.
                engine.__class__ = answer_tts.TTSEngine
        if 'original' not in studio.engines and 'emphasized' in studio.engines:
            studio.engines['original'] = studio.engines['emphasized']
        old_factory = getattr(previous, 'engine_factory', None)
        if old_factory is not None and getattr(old_factory, '__name__', '') != '_default_engine':
            studio.engine_factory = old_factory
        if hasattr(previous, 'executor'):
            studio.executor.shutdown(wait=False)
            studio.executor = previous.executor
        for key, old_editor in previous.editors.items():
            # Text/settings are already persisted by the existing editor.
            studio.answer(*key)
            editor = studio.editors[key]
            preview = getattr(old_editor, '_preview', None)
            if preview is not None and preview.signature == answer_review.fingerprint(editor.settings()):
                editor.show_preview(preview)
            # Update the same model already displayed in VS Code/Jupyter, so an
            # open notebook also receives the new buttons without a kernel reset.
            old_root = old_editor.widget
            old_root.children = editor.widget.children
            editor.widget = old_root
    namespace['studio'] = studio
    return studio


def get_cell_studio(namespace):
    """Reuse loaded weights and upgrade existing outputs to text-free panels.
"""
    modules = []
    versions = []
    for name in ('answer_tts', 'answer_review', 'cell_answer_review'):
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        version = (path.stat().st_mtime_ns, path.stat().st_size)
        if getattr(module, '_loaded_cell_stamp', None) != version:
            module = importlib.reload(module)
            module._loaded_cell_stamp = version
        modules.append(module)
        versions.append(version)
    _, _, cell_review = modules
    stamp = tuple(versions)
    previous = namespace.get('cell_studio') or namespace.get('studio')
    if isinstance(previous, cell_review.CellAnswerStudio) and getattr(previous, '_cell_stamp', None) == stamp:
        return previous
    old_items = getattr(previous, 'panels', None) or getattr(previous, 'editors', {})
    if any(getattr(e, '_busy', False) for e in old_items.values()):
        raise RuntimeError('Wait for the active preview to finish, then rerun this cell.')
    if previous is not None:
        for old in old_items.values():
            settings = old.settings() if callable(old.settings) else old.settings
            previous.store.update_draft(old.answer, settings)
    root = previous.store.project_root if previous is not None else cell_review.ROOT
    studio = cell_review.CellAnswerStudio(project_root=root)
    studio._cell_stamp = stamp
    if previous is not None:
        studio.engines = dict(previous.engines)
        studio.engine_factory = previous.engine_factory
        studio.executor.shutdown(wait=False)
        studio.executor = previous.executor
        studio.playback = previous.playback
        for key, old in old_items.items():
            settings = old.settings() if callable(old.settings) else old.settings
            preview = getattr(old, 'preview', None) or getattr(old, '_preview', None)
            panel = cell_review.AnswerPlaybackPanel(studio, studio.find_answer(*key), settings, preview)
            old.widget.children = panel.widget.children
            panel.widget = old.widget
            studio.panels[key] = panel
    namespace['studio'] = studio
    namespace['cell_studio'] = studio
    return studio
