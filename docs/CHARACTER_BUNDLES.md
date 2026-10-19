# Preparing a character

Import a ZIP containing exactly one `manifest.json`, a Blender project, and any packed assets. Bundle paths must be relative. ZIP symlinks and paths outside the bundle are rejected. Blender opens with `--disable-autoexec`.

Required manifest fields: `character_id`, `display_name`, `blend_file`, `minimum_blender_version`, `maximum_blender_version`, `scene`, `camera`, and `viseme_map`. Map every Rhubarb cue A, B, C, D, E, F, G, H, X to an existing mesh shape key. Shape-key names must be unique across mouth meshes unless the same pose intentionally drives all of them.

Optional idle animation uses `idle_action` plus `rig_object`. Use a prepared camera that frames the character in a square transparent canvas. The editor controls the canvas width and its top-left screen position. All textures/fonts should be packed into the .blend; do not use external scripts or simulation dependencies.

Run `blender --background --python sample-character/create_character.py` to create the supplied simple sample. Zip `presenter.blend` and `manifest.json` together, then import and validate in the app. The sample is an original procedural character, not an arbitrary artist rig.
