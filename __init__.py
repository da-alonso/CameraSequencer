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
    "version": (0, 0, 1),
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
    

# ------------------------------------------------------------------------
#    Operators
# ------------------------------------------------------------------------

class CAMERASEQUENCER_OT_PlaySequence(Operator):
    bl_label = "Play Sequence"
    bl_idname = "camera_sequencer.play_sequence"
    bl_description = "Play/Stop Sequencer"

    def execute(self, context):
        activate_camera_view()
        bpy.ops.screen.animation_play()
        camseq = context.scene.camsequencer_tool
        camseq.sequencer_is_playing = not camseq.sequencer_is_playing
        return {'FINISHED'}

class CAMERASEQUENCER_OT_PreviousShot(Operator):
    bl_label = "Previous Shot"
    bl_idname = "camera_sequencer.previous_shot"
    bl_description = "Jump to previous shot"

    def execute(self, context):
        activate_camera_view()
        scene = context.scene
        all_strips = list(sorted(scene.sequence_editor.sequences, key=lambda x:x.frame_final_start, reverse=True))
        for strip in all_strips:
            if strip.frame_final_start < scene.frame_current:
                scene.frame_current = strip.frame_final_start
                break        
        return {'FINISHED'}

class CAMERASEQUENCER_OT_NextShot(Operator):
    bl_label = "Next Shot"
    bl_idname = "camera_sequencer.next_shot"
    bl_description = "Jump to next shot"

    def execute(self, context):
        activate_camera_view()        
        scene = context.scene
        all_strips = list(sorted(scene.sequence_editor.sequences, key=lambda x:x.frame_final_start))
        for strip in all_strips:
            if strip.frame_final_start > scene.frame_current:
                scene.frame_current = strip.frame_final_start
                break
        return {'FINISHED'}

class CAMERASEQUENCER_OT_AddShot(Operator):
    bl_label = "Add Shot"
    bl_idname = "camera_sequencer.add_shot"
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
    bl_label = "Asign camera to selected strip"
    bl_idname = "camera_sequencer.assign_strip_camera"
    camera: StringProperty()

    def execute(self, context):
        se = context.scene.sequence_editor
        if se.active_strip:
            new_strip_name = update_shot_name(se.active_strip.name, self.camera)
            se.active_strip.name = new_strip_name
            camera_sequencer_handler(context.scene)
        return {'FINISHED'}


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


# ------------------------------------------------------------------------
#    Custoom functions
# ------------------------------------------------------------------------

def activate_camera_view():
    """Turns on camera view"""
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces[0].region_3d.view_perspective = 'CAMERA'
            break

def get_all_sequencer_strips():
    """Returns a sorted list of Sequencer's camera related strips"""
    sequencer_strips = []
    for strip in bpy.context.scene.sequence_editor.sequences:
        if strip.type == "COLOR" and re.match("sh_\d+\(.*\)", strip.name):
            sequencer_strips.append(strip)
    return sorted(sequencer_strips, key=lambda x:x.frame_final_start)

def create_new_shot_name(camera=""):
    """Returns string with shot name based on camera name"""
    shot_number = len(get_all_sequencer_strips()) + 1
    new_shot_name = "sh_%s(%s)"%(shot_number, camera)
    return new_shot_name

def update_shot_name(old_name, camera):
    """Returns string replacing the camera part of the shot name"""
    new_name = re.sub(r"\(.*\)", "(%s)"%camera, old_name)
    return new_name

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
    CAMERASEQUENCER_MT_cameras,
    CAMERASEQUENCER_PT_panel
)

def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
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