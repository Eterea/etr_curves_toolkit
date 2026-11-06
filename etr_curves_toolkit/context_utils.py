# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Context helpers shared by the tools of Curve Toolkit.

Most tools edit splines by rebuilding them (see spline_data.py), which is
only safe in Object Mode. edit_scope() hides that detail: tools that work on
the selected points of the Edit Mode simply wrap their work in it.
"""

from contextlib import contextmanager

import bpy
from mathutils import Vector

EDIT_MODE = 'EDIT_CURVE'

# Deepest parent chain world_matrix() walks (a safety net against a cycle).
_PARENT_DEPTH = 64


def is_curve(obj):
    return obj is not None and obj.type == 'CURVE'


def has_active_curve(context):
    return is_curve(context.active_object)


def selected_curves(context):
    """Selected curve objects (Object Mode)."""
    return [o for o in context.selected_objects if is_curve(o)]


def curves_in_edit_mode(context):
    """Curve objects being edited (Edit Mode supports multi-object editing)."""
    return [o for o in context.objects_in_mode_unique_data if is_curve(o)]


@contextmanager
def edit_scope(context, reenter=True):
    """Leave the Curve Edit Mode for the duration of the block.

    Yields the list of curve objects that were in Edit Mode. Selection flags of
    the points are flushed to the data when leaving, so they can be read.
    When the block ends the Edit Mode is entered again (unless reenter=False,
    which tools that hide the edited objects use).
    """
    objs = curves_in_edit_mode(context)
    active = context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    try:
        yield objs
    finally:
        if reenter and active is not None and active.name in context.view_layer.objects:
            try:
                for o in objs:
                    o.select_set(True)
                context.view_layer.objects.active = active
                bpy.ops.object.mode_set(mode='EDIT')
            except RuntimeError:
                pass


def resolution_source(context):
    """What the Resolution field of the panel reads and writes, or None.

    The curve data, the value that the Object Data properties show, which
    Blender hands to every spline of the curve as soon as it is changed. Only
    when a spline has really been made active in Edit Mode does the field show
    that spline instead, the way Sidebar > Item does, since that is the one it
    would be expected to talk about.
    """
    obj = getattr(context, "active_object", None)
    if not is_curve(obj):
        return None
    if context.mode == EDIT_MODE:
        active = obj.data.splines.active
        if active is not None:
            return active
    return obj.data


def world_matrix(obj):
    """World matrix of `obj`, computed from its transform data.

    Object.matrix_world is runtime data: the depsgraph fills it in when the
    scene is evaluated. An operator that runs again from the Adjust Last
    Operation panel (or F9) runs right after the undo step and before the next
    evaluation, where that matrix can still be the identity. Reading it there
    used to send the results of Offset and the Booleans to the world origin.

    matrix_basis (the location, rotation and scale of the object, deltas
    included) and matrix_parent_inverse are real data, so they can be read at
    any moment. Objects parented to a bone or to vertices, and objects with
    constraints, are not covered by that walk: for those matrix_world is still
    the only answer and is used as it comes.
    """
    matrix = obj.matrix_basis.copy()
    node = obj
    for _ in range(_PARENT_DEPTH):
        if node.constraints:
            return obj.matrix_world.copy()
        parent = node.parent
        if parent is None:
            return matrix
        if node.parent_type != 'OBJECT':
            return obj.matrix_world.copy()
        matrix = parent.matrix_basis @ node.matrix_parent_inverse @ matrix
        node = parent
    return obj.matrix_world.copy()


def world_point(obj, co):
    return world_matrix(obj) @ Vector(co)


def world_distance(obj, a, b):
    """Distance between two local-space points, measured in world space."""
    mw = world_matrix(obj)
    return ((mw @ Vector(a)) - (mw @ Vector(b))).length


def link_like(new_obj, source_obj, context):
    """Link `new_obj` into the first collection of `source_obj`."""
    colls = source_obj.users_collection
    (colls[0] if colls else context.scene.collection).objects.link(new_obj)


def new_curve_object(context, source_obj, spline_datas, name):
    """New curve object that shares the look of `source_obj` (bevel,
    materials, resolution...) and the given splines. It sits where the source
    sits, with no parent of its own. Returns the object (not yet linked).

    The placement goes through matrix_basis, so that it is stored as the
    location, rotation and scale of the object instead of waiting for the
    depsgraph (see world_matrix)."""
    from . import spline_data

    curve = source_obj.data.copy()
    curve.name = name
    spline_data.replace_splines(curve, spline_datas)
    obj = bpy.data.objects.new(name, curve)
    obj.matrix_basis = world_matrix(source_obj)
    return obj


# -----------------------------------------------------------------------------
# Sources and results of the Booleans and Splits
# -----------------------------------------------------------------------------

SOURCES_COLLECTION = "Curve Boolean Sources"
RESULTS_COLLECTION = "Curve Boolean Results"


def _collection_in_scene(scene, coll):
    return any(c == coll for c in scene.collection.children_recursive)


def named_collection(context, name, parent):
    """The collection called `name`, reused wherever it is in the scene, or a
    new one created inside `parent`."""
    coll = bpy.data.collections.get(name)
    if coll is not None and coll.library is None:
        if not _collection_in_scene(context.scene, coll):
            parent.children.link(coll)
        return coll
    coll = bpy.data.collections.new(name)
    parent.children.link(coll)
    return coll


def move_to_collection(obj, coll):
    """Move `obj` into `coll` (linking first, so it never leaves the scene)."""
    if coll not in obj.users_collection:
        coll.objects.link(obj)
    for c in list(obj.users_collection):
        if c != coll:
            c.objects.unlink(obj)


def layer_collection(view_layer, coll):
    """The LayerCollection of `coll` in the view layer, or None."""
    stack = [view_layer.layer_collection]
    while stack:
        lc = stack.pop()
        if lc.collection == coll:
            return lc
        stack.extend(lc.children)
    return None


_LAYER_FLAGS = ("exclude", "hide_viewport", "holdout", "indirect_only")


def keep_sources_above_results(context):
    """Put "Curve Boolean Sources" above "Curve Boolean Results" in the
    Outliner when both share a parent and the results came first (e.g. the
    results collection was made before "Place Sources inside a Collection" was
    turned on, or by an older version).

    The Python API cannot reorder the children of a collection, so the results
    collection is unlinked and linked again (it goes to the end of the list).
    Its View Layer settings and the hidden state of its objects are restored
    in every View Layer of the scene.
    """
    sources = bpy.data.collections.get(SOURCES_COLLECTION)
    results = bpy.data.collections.get(RESULTS_COLLECTION)
    if sources is None or results is None:
        return
    scene = context.scene
    for parent in [scene.collection, *scene.collection.children_recursive]:
        children = list(parent.children)
        if sources in children and results in children:
            break
    else:
        return
    if children.index(sources) < children.index(results):
        return

    saved = []
    for vl in scene.view_layers:
        lc = layer_collection(vl, results)
        if lc is None:
            continue
        flags = {f: getattr(lc, f) for f in _LAYER_FLAGS}
        hidden = []
        for obj in results.all_objects:
            try:
                if obj.hide_get(view_layer=vl):
                    hidden.append(obj)
            except RuntimeError:
                pass
        saved.append((vl, flags, hidden))

    parent.children.unlink(results)
    parent.children.link(results)

    for vl, flags, hidden in saved:
        lc = layer_collection(vl, results)
        if lc is None:
            continue
        for f, value in flags.items():
            if getattr(lc, f) != value:
                setattr(lc, f, value)
        for obj in hidden:
            try:
                obj.hide_set(True, view_layer=vl)
            except RuntimeError:
                pass


def finish_sources_and_results(context, sources, results, anchor=None):
    """Common ending of the Booleans and Splits (and Split at Control Points,
    Split at Stray Points).

    sources: the original objects. With "Place Sources inside a Collection"
             they are moved into "Curve Boolean Sources", and that collection
             is excluded from the View Layer (the checkbox before the eye in
             the Outliner) instead of hiding them one by one: it is enabled
             while new sources go in and excluded again at the end. Without
             that option they are hidden.
    results: list of (new object, source object). They are linked next to
             their source or, with "Place Results inside a Collection", into
             "Curve Boolean Results". Then they are selected.
    New collections are created inside the collection of `anchor` (by default
    the active object, or the first source). Existing ones are reused wherever
    they are; the visibility of the results collection is never changed.
    """
    settings = context.scene.etr_curves_toolkit
    if anchor is None:
        anchor = context.active_object if context.active_object in sources else sources[0]
    parent = anchor.users_collection[0] if anchor.users_collection else context.scene.collection

    # The sources collection is created first, so it sits above the results
    # one in the Outliner.
    sources_coll = None
    if settings.sources_in_collection:
        sources_coll = named_collection(context, SOURCES_COLLECTION, parent)

    if settings.results_in_collection:
        coll = named_collection(context, RESULTS_COLLECTION, parent)
        for obj, _ in results:
            coll.objects.link(obj)
    else:
        for obj, src in results:
            link_like(obj, src, context)

    for obj in context.selected_objects:
        obj.select_set(False)

    if sources_coll is not None:
        coll = sources_coll
        lc = layer_collection(context.view_layer, coll)
        if lc is not None:
            lc.exclude = False
        for obj in sources:
            move_to_collection(obj, coll)
            try:
                obj.hide_set(False)   # shown again whenever the collection is
            except RuntimeError:
                pass
        if lc is not None:
            lc.exclude = True
    else:
        for obj in sources:
            try:
                obj.hide_set(True)
            except RuntimeError:
                pass   # not in the View Layer (e.g. its collection is excluded)
    keep_sources_above_results(context)
    last = None
    for obj, _ in results:
        try:
            obj.select_set(True)
            last = obj
        except RuntimeError:
            pass
    if last is not None:
        context.view_layer.objects.active = last
