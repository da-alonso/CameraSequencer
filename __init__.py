# -*- coding:utf-8 -*-

#  ***** GPL LICENSE BLOCK *****
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#  All rights reserved.
#  ***** GPL LICENSE BLOCK *****

import bpy
from bpy.app.handlers import persistent
import re

bl_info = {
    "name": "Camera Sequencer",
    "description": "Adds real time camera editing to the Sequencer",
    "author": "David Alonso",
    "version": (0, 2, 1),
    "blender": (2, 83, 0),
    "location": "Video Sequencer > Cam Sequencer",
    "warning": "",
    "wiki_url": "",
    "tracker_url": "https://github.com/da-alonso/CameraSequencer/issues",
    "category": "Sequencer"
}


from bpy.props import (StringProperty,
                       BoolProperty,
                       IntProperty,
                       FloatProperty,
                       FloatVectorProperty,
                       EnumProperty,
                       PointerProperty,
                       )
from bpy.types import (Panel,
                       Menu,
                       Operator,
                       Macro,
                       PropertyGroup,
                       )


# ------------------------------------------------------------------------
#    Scene Properties
# ------------------------------------------------------------------------

class CameraSequencer_Properties(PropertyGroup):
    skip_gaps: BoolProperty(
        name="Skip gaps",
        description="Skip gaps between camera strips during playback",
        default = True
        )

    shot_duration: IntProperty(
        name = "Duration",
        description="Frame duration for new shots",
        default = 50,
        min = 1,
        max = 9999
        )

    sequencer_is_playing: BoolProperty(
        default = False
    )

    last_active_camera: StringProperty(
        default = ""
    )

    dragging_range_start: IntProperty(
        default = 0
    )

    dragging_range_end: IntProperty(
        default = 0
    )


# ------------------------------------------------------------------------
#    Operators
# ------------------------------------------------------------------------

class CAMERASEQUENCER_OT_PlaySequence(Operator):
    bl_idname = "camera_sequencer.play_sequence"
    bl_label = "Play Sequence"
    bl_description = "Play/Stop Sequencer"

    def execute(self, context):
        start, end = get_full_timeline_range()
        set_timeline_range(start, end)
        activate_camera_view()
        bpy.ops.screen.animation_play()
        camseq = context.scene.camsequencer_tool
        camseq.sequencer_is_playing = not camseq.sequencer_is_playing
        return {'FINISHED'}

class CAMERASEQUENCER_OT_PreviousShot(Operator):
    bl_idname = "camera_sequencer.previous_shot"
    bl_label = "Previous Shot"
    bl_description = "Jump to previous shot"
    set_range: bpy.props.BoolProperty(
        name="Set range", description="Set timeline range to strip's range", default=False
    )

    def execute(self, context):
        activate_camera_view()
        scene = context.scene
        for strip in get_all_sequencer_strips(reverse=True):
            if strip.frame_final_start < scene.frame_current:
                scene.frame_current = strip.frame_final_start
                break
        if self.set_range:
            set_range_and_frame(strip.frame_final_start, strip.frame_final_end)
            self.set_range = False # Toggle it back so the property doesn't stick
        return {'FINISHED'}

class CAMERASEQUENCER_OT_NextShot(Operator):
    bl_idname = "camera_sequencer.next_shot"
    bl_label = "Next Shot"
    bl_description = "Jump to next shot"
    set_range: bpy.props.BoolProperty(
        name="Set range", description="Set timeline range to strip's range", default=False
    )

    def execute(self, context):
        activate_camera_view()        
        scene = context.scene
        for strip in get_all_sequencer_strips():
            if strip.frame_final_start > scene.frame_current:
                scene.frame_current = strip.frame_final_start
                break
        if self.set_range:
            set_range_and_frame(strip.frame_final_start, strip.frame_final_end)
            self.set_range = False # Toggle it back so the property doesn't stick
        return {'FINISHED'}

class CAMERASEQUENCER_OT_AddShot(Operator):
    bl_idname = "camera_sequencer.add_shot"
    bl_label = "Add Shot"
    bl_description = "Add shot strip to the Sequencer"

    def execute(self, context):
        scene = context.scene
        camseq = scene.camsequencer_tool
        start = scene.frame_current
        end = start + camseq.shot_duration
        bpy.ops.sequencer.effect_strip_add(type='COLOR', frame_start=start, frame_end=end, channel=2, color=(0.3,0.6,0.6))
        scene.sequence_editor.active_strip.name = create_new_shot_name()
        return {'FINISHED'}

class CAMERASEQUENCER_OT_AssignCamera(Operator):
    bl_idname = "camera_sequencer.assign_strip_camera"
    bl_label = "Asign camera to selected strip"
    camera: StringProperty()

    def execute(self, context):
        se = context.scene.sequence_editor
        if se.active_strip:
            new_strip_name = update_shot_name(se.active_strip.name, self.camera)
            se.active_strip.name = new_strip_name
            camera_sequencer_handler(context.scene)
        return {'FINISHED'}

class End(Operator):
    bl_idname = "dragkeys.end"
    bl_label = "Finish dragging strip"

    def execute(self, context):
        camseq = context.scene.camsequencer_tool
        finish_range_start, finish_range_end = get_selected_range()
        offset = finish_range_start - camseq.dragging_range_start
        orig_range = [camseq.dragging_range_start, camseq.dragging_range_end]
        move_all_keys(orig_range, offset)
        move_all_greasepencil_keys(orig_range, offset)
        refresh_dopesheet() # Greasepencil's dopesheet doesn't auto-refresh
        return {'FINISHED'}

class Start(Operator):
    bl_idname = "dragkeys.start"
    bl_label = "Start dragging strip"

    def execute(self, context):
        camseq = context.scene.camsequencer_tool
        sel_range = get_selected_range()
        camseq.dragging_range_start, camseq.dragging_range_end = sel_range
        deselect_strip_handles()
        select_strips_in_range(sel_range)
        return {'FINISHED'}

class DRAGKEYS(Macro):
    bl_idname = "dragkeys.trigger_macro"
    bl_label = "Drag strip and keys macro"
    bl_options = {'REGISTER', 'UNDO'}


# ------------------------------------------------------------------------
#    UI
# ------------------------------------------------------------------------

class CAMERASEQUENCER_MT_cameras(Menu):
    bl_label = "Cameras"
    bl_idname = 'CAMERASEQUENCER_MT_cameras'

    def draw(self, context):
        layout = self.layout
        for obj in bpy.data.objects:
            if obj.type == "CAMERA":
                layout.operator("camera_sequencer.assign_strip_camera", text=obj.name).camera=obj.name

class CAMERASEQUENCER_PT_panel(Panel):
    bl_label = "Camera Sequencer"
    bl_idname = "OBJECT_PT_camera_sequencer"
    bl_space_type = "SEQUENCE_EDITOR"   
    bl_region_type = "UI"
    bl_category = "Cam Seq"
    bl_context = "objectmode"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        camseq = scene.camsequencer_tool

        row = layout.row()
        subrow = row.row(align=True)
        subrow.operator("camera_sequencer.previous_shot", text="", icon="REW")
        play_icon = "PAUSE" if bpy.context.screen.is_animation_playing else "PLAY"
        subrow.operator("camera_sequencer.play_sequence", text="", icon=play_icon)
        subrow.operator("camera_sequencer.next_shot", text="", icon="FF")
        row.prop(camseq, "skip_gaps")
        row = layout.row()
        row.operator("camera_sequencer.add_shot", text="Add Shot", icon="FILE_MOVIE")
        row.prop(camseq, "shot_duration")
        layout.menu(CAMERASEQUENCER_MT_cameras.bl_idname, text="Cameras", icon="OUTLINER_OB_CAMERA")
        """Move this to its own panel of shot (strip) properties
        # Only display camera selector if there's a strip selected
        if context.scene.sequence_editor.active_strip:
            layout.menu(CAMERASEQUENCER_MT_cameras.bl_idname, text="Cameras", icon="OUTLINER_OB_CAMERA")
        """

# ------------------------------------------------------------------------
#    Custom functions
# ------------------------------------------------------------------------

def activate_camera_view():
    """Turns on camera view"""
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces[0].region_3d.view_perspective = 'CAMERA'
            break

def get_all_sequencer_strips(reverse=False):
    """Returns a sorted list of Sequencer's camera related strips"""
    sequencer_strips = []
    for strip in bpy.context.scene.sequence_editor.sequences:
        if strip.type == "COLOR" and re.match("sh_\d+\(.*\)", strip.name):
            sequencer_strips.append(strip)
    return sorted(sequencer_strips, key=lambda x:x.frame_final_start, reverse=reverse)

def get_full_timeline_range():
    """Gets the range of timeline containing all strips"""
    strips = get_all_sequencer_strips()
    lowest_start = strips[0].frame_final_start
    highest_end = strips[-1].frame_final_end
    return [lowest_start, highest_end]

def set_timeline_range(start, end):
    """Changes animation timeline range"""
    bpy.context.scene.frame_start = start
    bpy.context.scene.frame_end = end

def create_dummy_obj_keys(start, end):
    """Returns a dummy object with two keyframes"""
    bpy.ops.object.empty_add()
    obj = bpy.context.active_object
    obj.keyframe_insert(data_path="location", frame=start)
    obj.keyframe_insert(data_path="location", frame=end)
    return obj

def create_dummy_gp_keys(start, end):
    """Returns a dummy greasepencil object with two keyframes"""
    bpy.ops.object.gpencil_add()
    gpencil = bpy.context.active_object
    layer = gpencil.data.layers.new(name='dummy')
    layer.frames.new(start)
    layer.frames.new(end)
    return gpencil

def context_override(area):
    """Overrides current context to set it to area"""
    region = area.regions[-1]
    c = bpy.context.copy()
    c["space_data"] = area.spaces.active
    c["area"] = area
    c["region"] = region
    return c

def frame_all_dopesheets_range(start, end):
    """Frames all dopesheet-type areas to a frame range.
    I'm actually repulsed by this code but it seems
    there's no easier way of framing timelines in Blender :/
    """
    for area in bpy.context.screen.areas:
        if area.type != 'DOPESHEET_EDITOR':
            continue

        if area.ui_type in ['DOPESHEET', 'TIMELINE', 'GPENCIL']:
            dummy_obj = create_dummy_gp_keys(start, end) if area.ui_type == 'GPENCIL' else create_dummy_obj_keys(start, end) 
            c = context_override(area) # Context override
            bpy.ops.action.view_all(c) # Frame all keyframes
            bpy.data.objects.remove(dummy_obj)

def set_range_and_frame(start, end):
    """Changes animation timeline range and frames it"""
    set_timeline_range(start, end)
    frame_all_dopesheets_range(start, end)

def deselect_strip_handles():
    """Deselects all strips' handles"""
    for strip in bpy.context.scene.sequence_editor.sequences:
        strip.select_left_handle = False
        strip.select_right_handle = False

def select_strips_in_range(frame_range):
    """Selects all strips contained in a frame range"""
    for strip in get_all_sequencer_strips():
        if frame_range[0] <= strip.frame_final_end <= frame_range[1]:
            strip.select = True

def create_new_shot_name(camera=""):
    """Returns string with shot name based on camera name"""
    shot_number = len(get_all_sequencer_strips()) + 1
    new_shot_name = "sh_%s(%s)"%(shot_number, camera)
    return new_shot_name

def update_shot_name(old_name, camera):
    """Returns string replacing the camera part of the shot name"""
    new_name = re.sub(r"\(.*\)", "(%s)"%camera, old_name)
    return new_name

def move_all_keys(frame_range, offset):
    """Offsets the time of all keyframes in a range"""
    for action in bpy.data.actions:
        for fcurve in action.fcurves:
            for point in fcurve.keyframe_points:
                if frame_range[0] <= point.co.x <= frame_range[1]:
                    point.co.x += offset
                    point.handle_left.x += offset
                    point.handle_right.x += offset

def move_all_greasepencil_keys(frame_range, offset):
    """Offsets the time of all greasepencil keyframes in a range"""
    for obj in bpy.context.scene.objects:
        if obj.type == 'GPENCIL':
            gpencil = bpy.context.scene.objects[obj.name]
            for layer in gpencil.data.layers:
                for frame in layer.frames:
                    if frame_range[0] <= frame.frame_number <= frame_range[1]:
                        frame.frame_number += offset

def refresh_dopesheet():
    """Forces redraw of all dopesheet areas"""
    for area in bpy.context.screen.areas:
        if area.ui_type == 'DOPESHEET':
            area.tag_redraw()

def get_selected_range():
    """Returns maximum frame range of selected strips"""
    selected_strips = [x for x in bpy.context.scene.sequence_editor.sequences if x.select]
    selected_strips = sorted(selected_strips, key=lambda x:x.frame_final_start)
    lowest_frame = selected_strips[0].frame_final_start
    highest_frame = selected_strips[-1].frame_final_end
    return [lowest_frame, highest_frame]

@persistent
def camera_sequencer_handler(scene):
    """Checks for timeline changes to switch active camera"""
    camseq = scene.camsequencer_tool
    # If animation is not playing turn off internal playing flag to avoid skipping gaps while scrubbing
    if not bpy.context.screen.is_animation_playing:
        camseq.sequencer_is_playing = False
    
    playhead_over_strip = False
    closest_strip_start = -9999
    all_strips = get_all_sequencer_strips()
    for strip in all_strips:
        if strip.frame_final_start <= scene.frame_current <= strip.frame_final_end:
            m = re.search("sh_\d+\((.+)\)", strip.name)
            if m:
                camera_name = m.group(1)
                if bpy.context.scene.objects.get(camera_name) and camera_name != camseq.last_active_camera:
                    camera_obj = bpy.data.objects[camera_name]
                    scene.camera = camera_obj
                    camseq.last_active_camera = camera_name
                playhead_over_strip = True
            break
        elif strip.frame_final_start > scene.frame_current and closest_strip_start == -9999:
            closest_strip_start = strip.frame_final_start

    # Move the playhead to skip gap if applicable
    if not playhead_over_strip and camseq.skip_gaps and camseq.sequencer_is_playing:
        scene.frame_current = closest_strip_start


# ------------------------------------------------------------------------
#    Registration
# ------------------------------------------------------------------------

classes = (
    CameraSequencer_Properties,
    CAMERASEQUENCER_OT_PlaySequence,
    CAMERASEQUENCER_OT_PreviousShot,
    CAMERASEQUENCER_OT_NextShot,
    CAMERASEQUENCER_OT_AddShot,
    CAMERASEQUENCER_OT_AssignCamera,
    End,
    Start,
    DRAGKEYS,
    CAMERASEQUENCER_MT_cameras,
    CAMERASEQUENCER_PT_panel
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)

    # Configure macro for moving keyframes while dragging strips
    DRAGKEYS.define("DRAGKEYS_OT_start")
    DRAGKEYS.define("TRANSFORM_OT_translate")
    DRAGKEYS.define("DRAGKEYS_OT_end")

    # Add shortcuts
    wm = bpy.context.window_manager
    km = wm.keyconfigs.addon.keymaps.new(name='Window', space_type='EMPTY', region_type='WINDOW')
    kmi = km.keymap_items.new(CAMERASEQUENCER_OT_PreviousShot.bl_idname, 'LEFT_ARROW', 'PRESS', ctrl=True)
    kmi = km.keymap_items.new(CAMERASEQUENCER_OT_NextShot.bl_idname, 'RIGHT_ARROW', 'PRESS', ctrl=True)
    kmi = km.keymap_items.new(CAMERASEQUENCER_OT_PreviousShot.bl_idname, 'LEFT_ARROW', 'PRESS', ctrl=True, shift=True)
    setattr(kmi.properties, 'set_range', True)
    kmi = km.keymap_items.new(CAMERASEQUENCER_OT_NextShot.bl_idname, 'RIGHT_ARROW', 'PRESS', ctrl=True, shift=True)
    setattr(kmi.properties, 'set_range', True)
    km = wm.keyconfigs.addon.keymaps.new(name='Sequencer', space_type='SEQUENCE_EDITOR')
    kmi = km.keymap_items.new(DRAGKEYS.bl_idname, 'G', 'PRESS', alt=True)

    bpy.types.Scene.camsequencer_tool = PointerProperty(type=CameraSequencer_Properties)
    bpy.app.handlers.frame_change_post.append(camera_sequencer_handler)

def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    del bpy.types.Scene.camsequencer_tool
    bpy.app.handlers.frame_change_post.remove(camera_sequencer_handler)

if __name__ == "__main__":
    register()