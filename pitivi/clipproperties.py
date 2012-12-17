# PiTiVi , Non-linear video editor
#
#       clipproperties.py
#
# Copyright (C) 2010 Thibault Saunier <tsaunier@gnome.org>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA 02110-1301, USA.

"""
Class handling the midle pane
"""
import os

from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import Pango
from gi.repository import GES

from gettext import gettext as _

from pitivi.check import missing_soft_deps
from pitivi.configure import get_ui_dir

from pitivi.dialogs.depsmanager import DepsManager

from pitivi.utils.ui import EFFECT_TARGET_ENTRY
from pitivi.utils.loggable import Loggable
from pitivi.utils.ui import PADDING, SPACING
from pitivi.utils.widgets import GstElementSettingsWidget

from pitivi.effects import AUDIO_EFFECT, VIDEO_EFFECT, HIDDEN_EFFECTS, \
    EffectsPropertiesManager

(COL_ACTIVATED,
 COL_TYPE,
 COL_NAME_TEXT,
 COL_DESC_TEXT,
 COL_TRACK_EFFECT) = range(5)


class ClipPropertiesError(Exception):
    """Base Exception for errors happening in L{ClipProperties}s or L{EffectProperties}s"""
    pass


def compare_type(track, effect_type):

    if (track.get_property("track_type") == GES.TrackType.AUDIO
    and effect_type == AUDIO_EFFECT):
        return True
    elif (track.get_property("track_type") == GES.TrackType.VIDEO
    and effect_type == VIDEO_EFFECT):
        return True
    return False


class ClipProperties(Gtk.ScrolledWindow, Loggable):
    """
    Widget for configuring clips properties
    """

    def __init__(self, instance, uiman):
        Gtk.ScrolledWindow.__init__(self)
        Loggable.__init__(self)
        self.app = instance
        self.settings = instance.settings
        self._project = None

        self.infobar_box = Gtk.VBox()
        effect_properties_handling = EffectsPropertiesManager(instance)
        self.effect_expander = EffectProperties(instance, effect_properties_handling, self)
        self.transformation_expander = TransformationProperties(instance, instance.action_log)
        self.effect_expander.set_vexpand(False)
        self.transformation_expander.set_vexpand(False)

        vbox = Gtk.VBox()
        vbox.set_spacing(SPACING)
        vbox.pack_start(self.infobar_box, False, True, 0)
        vbox.pack_start(self.transformation_expander, False, True, 0)
        vbox.pack_start(self.effect_expander, True, True, 0)

        viewport = Gtk.Viewport()
        viewport.add(vbox)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.add(viewport)
        viewport.show()
        vbox.show()
        self.infobar_box.show()

    def _setProject(self, project):
        self._project = project
        if project:
            self.effect_expander._connectTimelineSelection(self._project.timeline)
            if self.transformation_expander:
                self.transformation_expander.timeline = self._project.timeline

    def _getProject(self):
        return self._project

    project = property(_getProject, _setProject)

    def addInfoBar(self, text):
        label = Gtk.Label(label=text)
        label.set_line_wrap(True)
        info_bar = Gtk.InfoBar()
        info_bar.get_content_area().add(label)
        self.infobar_box.pack_start(info_bar, False, False, 0)
        return info_bar

    def _getTimeline(self):
        return self._timeline

    def _setTimeline(self, timeline):
        self.effect_expander.timeline = timeline
        self.transformation_expander.timeline = timeline
        self._timeline = timeline

    timeline = property(_getTimeline, _setTimeline)


class EffectProperties(Gtk.Expander):
    """
    Widget for viewing and configuring effects
    """
    # Note: This should be inherited from Gtk.Expander when we get other things
    # to put in ClipProperties, that is why this is done this way

    def __init__(self, instance, effect_properties_handling, clip_properties):
        Gtk.Expander.__init__(self)

        self.selected_effects = []
        self.timeline_objects = []
        self._factory = None
        self.app = instance
        self.settings = instance.settings
        self.effectsHandler = self.app.effects
        self._effect_config_ui = None
        self.pipeline = None
        self.effect_props_handling = effect_properties_handling
        self.clip_properties = clip_properties
        self._info_bar = None
        self._config_ui_h_pos = None
        self._timeline = None

        self._vcontent = Gtk.VPaned()
        self.add(self._vcontent)

        self._table = Gtk.Table(3, 1, False)

        self._toolbar = Gtk.Toolbar()
        self._removeEffectBt = Gtk.ToolButton("gtk-delete")
        self._removeEffectBt.set_label(_("Remove effect"))
        self._removeEffectBt.set_use_underline(True)
        self._removeEffectBt.set_is_important(True)
        self._removeEffectBt.set_sensitive(False)
        self._toolbar.insert(self._removeEffectBt, 0)
        self._table.attach(self._toolbar, 0, 1, 0, 1, yoptions=Gtk.AttachOptions.FILL)

        self.storemodel = Gtk.ListStore(bool, str, str, str, object)

        #Treeview
        self.treeview_scrollwin = Gtk.ScrolledWindow()
        self.treeview_scrollwin.set_policy(Gtk.PolicyType.NEVER,
                                           Gtk.PolicyType.AUTOMATIC)
        self.treeview_scrollwin.set_shadow_type(Gtk.ShadowType.ETCHED_IN)

        # TreeView
        # Displays name, description
        self.treeview = Gtk.TreeView(self.storemodel)
        self.treeview_scrollwin.add(self.treeview)
        self.treeview.set_property("rules_hint", True)
        self.treeview.set_property("has_tooltip", True)
        tsel = self.treeview.get_selection()
        tsel.set_mode(Gtk.SelectionMode.SINGLE)

        activatedcell = Gtk.CellRendererToggle()
        activatedcell.props.xpad = PADDING
        activatedcell.connect("toggled", self._effectActiveToggleCb)

        typecol = Gtk.TreeViewColumn(_("Type"))
        typecol.set_sort_column_id(COL_TYPE)
        self.treeview.append_column(typecol)
        typecol.set_spacing(SPACING)
        typecol.set_sizing(Gtk.TreeViewColumnSizing.AUTOSIZE)
        typecell = Gtk.CellRendererText()
        typecell.props.xpad = PADDING
        typecell.set_property("ellipsize", Pango.EllipsizeMode.END)
        typecol.pack_start(typecell, True)
        typecol.add_attribute(typecell, "text", COL_TYPE)

        namecol = Gtk.TreeViewColumn(_("Effect name"))
        namecol.set_sort_column_id(COL_NAME_TEXT)
        self.treeview.append_column(namecol)
        namecol.set_spacing(SPACING)
        namecell = Gtk.CellRendererText()
        namecell.props.xpad = PADDING
        namecell.set_property("ellipsize", Pango.EllipsizeMode.END)
        namecol.pack_start(namecell, True)
        namecol.add_attribute(namecell, "text", COL_NAME_TEXT)

        self.treeview.drag_dest_set(Gtk.DestDefaults.MOTION,
            [EFFECT_TARGET_ENTRY],
            Gdk.DragAction.COPY)

        self.treeview.drag_dest_add_text_targets()

        self.selection = self.treeview.get_selection()

        self.selection.connect("changed", self._treeviewSelectionChangedCb)
        self._removeEffectBt.connect("clicked", self._removeEffectClicked)

        self.treeview.connect("drag-leave", self._dragLeaveCb)
        self.treeview.connect("drag-drop", self._dragDropCb)
        self.treeview.connect("drag-motion", self._dragMotionCb)
        self.treeview.connect("query-tooltip", self._treeViewQueryTooltipCb)
        self._vcontent.connect("notify", self._vcontentNotifyCb)
        self.treeview.set_headers_clickable(False)
        self.app.connect("new-project-loaded", self._newProjectLoadedCb)

        self._table.attach(self.treeview_scrollwin, 0, 1, 2, 3)

        self._vcontent.pack1(self._table, resize=True, shrink=False)
        self._showInfoBar()
        self._vcontent.show()
        self._table.show_all()
        self.set_expanded(True)
        self.set_label(_("Effects"))
        self.connect('notify::expanded', self._expandedCb)
        self.connected = False
        self.hide()

    def _newProjectLoadedCb(self, app, project):
        self.clip_properties.project = project
        self.selected_effects = self.timeline.selection.getSelectedTrackEffects()
        self.updateAll()

    def _vcontentNotifyCb(self, paned, gparamspec):
        if gparamspec and gparamspec.name == 'position':
            self._config_ui_h_pos = self._vcontent.get_position()
            self.settings.effectVPanedPosition = self._config_ui_h_pos

    def _getTimeline(self):
        return self._timeline

    def _setTimeline(self, timeline):
        if timeline:
            self._timeline = timeline
            self._timeline.selection.connect("selection-changed", self._selectionChangedCb)
            self.connected = True
        else:
            if self.connected:
                self._timeline.selection.disconnect_by_func(self._selectionChangedCb)

            self.connected = False
            self._timeline = None

    timeline = property(_getTimeline, _setTimeline)

    def _selectionChangedCb(self, selection,):
        for timeline_object in self.timeline_objects:
            timeline_object.disconnect_by_func(self._trackObjectAddedCb)
            timeline_object.disconnect_by_func(self._trackRemovedRemovedCb)

        self.selected_effects = selection.getSelectedTrackEffects()

        if selection.selected:
            self.timeline_objects = list(selection.selected)
            for timeline_object in self.timeline_objects:
                timeline_object.connect("track-object-added", self._trackObjectAddedCb)
                timeline_object.connect("track-object-removed", self._trackRemovedRemovedCb)
            self.show()
        else:
            self.timeline_objects = []
            self.hide()
        self.updateAll()

    def  _trackObjectAddedCb(self, unused_timeline_object, track_object):
        if isinstance(track_object, GES.TrackEffect):
            selec = self.timeline.selection.getSelectedTrackEffects()
            self.selected_effects = selec
            self.updateAll()

    def  _trackRemovedRemovedCb(self, unused_timeline_object, track_object):
        if isinstance(track_object, GES.TrackEffect):
            selec = self.timeline.selection.getSelectedTrackEffects()
            self.selected_effects = selec
            self.updateAll()

    def _connectTimelineSelection(self, timeline):
        self.timeline = timeline

    def _removeEffectClicked(self, toolbutton):
        if not self.selection.get_selected()[1]:
            return
        else:
            effect = self.storemodel.get_value(self.selection.get_selected()[1],
                                               COL_TRACK_EFFECT)
            self._removeEffect(effect)

    def _removeEffect(self, effect):
        self.app.action_log.begin("remove effect")
        self._cleanCache(effect)
        effect.get_track().remove_object(effect)
        effect.get_timeline_object().release_track_object(effect)
        self._updateTreeview()
        self.app.action_log.commit()

    def _cleanCache(self, effect):
        config_ui = self.effect_props_handling.cleanCache(effect)

    def addEffectToCurrentSelection(self, bin_desc):
        if self.timeline_objects:
            media_type = self.app.effects.getFactoryFromName(bin_desc).media_type

            # Trying to apply effect only on the first object of the selection
            tlobj = self.timeline_objects[0]

            # Checking that this effect can be applied on this track object
            # Which means, it has the corresponding media_type
            for tckobj in tlobj.get_track_objects():
                track = tckobj.get_track()
                if track.get_property("track_type") == GES.TrackType.AUDIO and \
                        media_type == AUDIO_EFFECT or \
                        track.get_property("track_type") == GES.TrackType.VIDEO and \
                        media_type == VIDEO_EFFECT:
                    #Actually add the effect
                    self.app.action_log.begin("add effect")
                    effect = GES.TrackParseLaunchEffect(bin_description=bin_desc)
                    tlobj.add_track_object(effect)
                    track.add_object(effect)
                    self.updateAll()
                    self.app.action_log.commit()
                    self.app.current.pipeline.flushSeek()

                    break

    def _dragDropCb(self, unused, context, unused_x, unused_y,
             unused_timestamp):
        self.addEffectToCurrentSelection(self.app.gui.effectlist.getSelectedItems())

    def _dragLeaveCb(self, unused_layout, unused_context, unused_tstamp):
        self.drag_unhighlight()

    def _dragMotionCb(self, unused, context, x, y, timestamp):
        self.drag_highlight()

    def _effectActiveToggleCb(self, cellrenderertoggle, path):
        iter = self.storemodel.get_iter(path)
        tck_effect = self.storemodel.get_value(iter, COL_TRACK_EFFECT)
        self.app.action_log.begin("change active state")
        tck_effect.set_active(not tck_effect.is_active())
        cellrenderertoggle.set_active(tck_effect.is_active())
        self._updateTreeview()
        self.app.action_log.commit()

    def _expandedCb(self, expander, params):
        self.updateAll()

    def _treeViewQueryTooltipCb(self, view, x, y, keyboard_mode, tooltip):
        is_row, x, y, model, path, iter_ = view.get_tooltip_context(x, y, keyboard_mode)

        if not is_row:
            return False

        # FIXME GObject Introspection, make sure forth is the path
        #view.set_tooltip_row(tooltip, path)

        return True

    def updateAll(self):
        if self.get_expanded():
            self._removeEffectBt.set_sensitive(False)
            if len(self.timeline_objects) == 1:
                self._setEffectDragable()
                self._updateTreeview()
                self._updateEffectConfigUi()
            else:
                self._hideEffectConfig()
                self.storemodel.clear()
                self._showInfoBar()
            self._vcontent.show()
        else:
            self._vcontent.hide()

    def _updateTreeview(self):
        self.storemodel.clear()

        obj = self.timeline_objects[0]
        for track_effect in obj.get_top_effects():
            if not track_effect.props.bin_description in HIDDEN_EFFECTS:
                material = self.app.effects.getFactoryFromName(
                    track_effect.props.bin_description)
                to_append = [track_effect.props.active]
                track = track_effect.get_track()
                if track.get_property("track_type") == GES.TrackType.AUDIO:
                    to_append.append("Audio")
                elif track.get_property("track_type") == GES.TrackType.VIDEO:
                    to_append.append("Video")

                to_append.append(track_effect.props.bin_description)
                to_append.append(material.description)
                to_append.append(track_effect)

                self.storemodel.append(to_append)

    def _showInfoBar(self):
        if self._info_bar is None:
            self._info_bar = self.clip_properties.addInfoBar(
                _("Select a clip on the timeline to configure its associated effects"))
        self._info_bar.show_all()

    def _setEffectDragable(self):
        self.show()
        self._info_bar.hide()

    def _treeviewSelectionChangedCb(self, treeview):
        if self.selection.count_selected_rows() == 0 and self.timeline_objects:
            self.app.gui.setActionsSensitive(True)
            self._removeEffectBt.set_sensitive(False)
        else:
            self.app.gui.setActionsSensitive(False)
            self._removeEffectBt.set_sensitive(True)

        self._updateEffectConfigUi()

    def _updateEffectConfigUi(self):
        if self._config_ui_h_pos is None:
            self._config_ui_h_pos = self.app.gui.settings.effectVPanedPosition
            if self._config_ui_h_pos is None:
                self._config_ui_h_pos = self.app.gui.settings.mainWindowHeight // 3

        if self.selection.get_selected()[1]:
            track_effect = self.storemodel.get_value(self.selection.get_selected()[1],
                                               COL_TRACK_EFFECT)

            for widget in self._vcontent.get_children():
                if type(widget) in [Gtk.ScrolledWindow, GstElementSettingsWidget]:
                    self._vcontent.remove(widget)

            element = track_effect
            ui = self.effect_props_handling.getEffectConfigurationUI(element)

            self._effect_config_ui = ui
            if self._effect_config_ui:
                self._vcontent.pack2(self._effect_config_ui, resize=False, shrink=False)
                self._vcontent.set_position(int(self._config_ui_h_pos))
                self._effect_config_ui.show_all()
            self.selected_on_treeview = track_effect
        else:
            self._hideEffectConfig()

    def _hideEffectConfig(self):
        if self._effect_config_ui:
            self._effect_config_ui.hide()
            self._effect_config_ui = None


class TransformationProperties(Gtk.Expander):
    """
    Widget for viewing and configuring speed
    """
    __signals__ = {
        'selection-changed': []}

    def __init__(self, app, action_log):
        Gtk.Expander.__init__(self)
        self.action_log = action_log
        self.app = app
        self._timeline = None
        self._current_tl_obj = None
        self.spin_buttons = {}
        self.default_values = {}
        self.set_label(_("Transformation"))

        if not "Frei0r" in missing_soft_deps:
            self.builder = Gtk.Builder()
            self.builder.add_from_file(os.path.join(get_ui_dir(),
                        "cliptransformation.ui"))

            self.add(self.builder.get_object("transform_box"))
            self.show_all()
            self._initButtons()
        self.connect('notify::expanded', self._expandedCb)
        self.hide()

    def _initButtons(self):
        self.zoom_scale = self.builder.get_object("zoom_scale")
        self.zoom_scale.connect("value-changed", self._zoomViewerCb)
        clear_button = self.builder.get_object("clear_button")
        clear_button.connect("clicked", self._defaultValuesCb)

        self._getAndConnectToEffect("xpos_spinbtn", "tilt_x")
        self._getAndConnectToEffect("ypos_spinbtn", "tilt_y")

        self._getAndConnectToEffect("width_spinbtn", "scale_x")
        self._getAndConnectToEffect("height_spinbtn", "scale_y")

        self._getAndConnectToEffect("crop_left_spinbtn", "clip_left")
        self._getAndConnectToEffect("crop_right_spinbtn", "clip_right")
        self._getAndConnectToEffect("crop_top_spinbtn", "clip_top")
        self._getAndConnectToEffect("crop_bottom_spinbtn", "clip_bottom")
        self.connectSpinButtonsToFlush()

    def _zoomViewerCb(self, scale):
        self.app.gui.viewer.setZoom(scale.get_value())

    def _expandedCb(self, expander, params):
        if not "Frei0r" in missing_soft_deps:
            if self._current_tl_obj:
                self.effect = self._findOrCreateEffect("frei0r-filter-scale0tilt")
                self._updateSpinButtons()
                self.set_expanded(self.get_expanded())
                self._updateBoxVisibility()
                self.zoom_scale.set_value(1.0)
        else:
            if self.get_expanded():
                DepsManager(self.app)
            self.set_expanded(False)

    def _defaultValuesCb(self, widget):
        self.disconnectSpinButtonsFromFlush()
        for name, spinbtn in self.spin_buttons.items():
            spinbtn.set_value(self.default_values[name])
        self.connectSpinButtonsToFlush()
        self.track_effect.gnl_object.props.active = False

    def disconnectSpinButtonsFromFlush(self):
        for spinbtn in self.spin_buttons.values():
            spinbtn.disconnect_by_func(self._flushPipeLineCb)

    def connectSpinButtonsToFlush(self):
        for spinbtn in self.spin_buttons.values():
            spinbtn.connect("output", self._flushPipeLineCb)

    def _updateSpinButtons(self):
        for name, spinbtn in self.spin_buttons.items():
            spinbtn.set_value(self.effect.get_property(name))

    def _getAndConnectToEffect(self, widget_name, property_name):
        """
        Create a spinbutton widget and connect its signals to change property
        values. While focused, disable the timeline actions' sensitivity.
        """
        spinbtn = self.builder.get_object(widget_name)
        spinbtn.connect("output", self._onValueChangedCb, property_name)
        spinbtn.connect("focus-in-event", self._disableTimelineActionsCb)
        spinbtn.connect("focus-out-event", self._enableTimelineActionsCb)
        self.spin_buttons[property_name] = spinbtn
        self.default_values[property_name] = spinbtn.get_value()

    def _onValueChangedCb(self, spinbtn, prop):
        value = spinbtn.get_value()

        if value != self.default_values[prop] and not self.track_effect.get_gnlobject().props.active:
            self.track_effect.get_gnlobject().props.active = True

        if value != self.effect.get_property(prop):
            self.action_log.begin("Transformation property change")
            self.effect.set_property(prop, value)
            self.action_log.commit()
        box = self.app.gui.viewer.internal.box

        # update box when values are changed in the spin boxes,
        # so no point is selected
        if box and box.clicked_point == 0:
            box.update_from_effect(self.effect)

    def _disableTimelineActionsCb(self, unused_widget, unused_event):
        self.app.gui.setActionsSensitive(False)

    def _enableTimelineActionsCb(self, unused_widget, unused_event):
        self.app.gui.setActionsSensitive(True)

    def _flushPipeLineCb(self, widget):
        self.app.current.pipeline.flushSeek()

    def _findEffect(self, name):
        for track_effect in self._current_tl_obj.get_track_objects():
            if isinstance(track_effect, GES.TrackParseLaunchEffect):
                if name in track_effect.get_property("bin-description"):
                        self.track_effect = track_effect
                        return track_effect.get_element()

    def _findOrCreateEffect(self, name):
        effect = self._findEffect(name)
        if not effect:
            effect = GES.TrackParseLaunchEffect(bin_description=name)
            self._current_tl_obj.add_track_object(effect)
            tracks = self.app.projectManager.current.timeline.get_tracks()
            for track in tracks:
                if track.get_caps().to_string() == "video/x-raw":
                    track.add_object(effect)
            effect = self._findEffect(name)
            # disable the effect on default
            a = self.track_effect.get_gnlobject()
            self.effect = list(list(a.elements())[0].elements())[1]
            self.track_effect.get_gnlobject().props.active = False
        self.app.gui.viewer.internal.set_transformation_properties(self)
        effect.freeze_notify()
        return self.effect

    def _selectionChangedCb(self, timeline):
        if self.timeline and len(self.timeline.selection.selected) > 0:
            for tl_obj in self.timeline.selection.selected:
                pass

            if tl_obj != self._current_tl_obj:
                self._current_tl_obj = tl_obj
                self.effect = None

            self.show()
            if self.get_expanded():
                self.effect = self._findOrCreateEffect("frei0r-filter-scale0tilt")
                self._updateSpinButtons()
        else:
            if self._current_tl_obj:
                self._current_tl_obj = None
                self.zoom_scale.set_value(1.0)
                self.app.current.pipeline.flushSeek()
            self.effect = None
            self.hide()
        self._updateBoxVisibility()

    def _updateBoxVisibility(self):
        if self.get_expanded() and self._current_tl_obj:
            self.app.gui.viewer.internal.show_box()
        else:
            self.app.gui.viewer.internal.hide_box()

    def _getTimeline(self):
        return self._timeline

    def _setTimeline(self, timeline):
        self._timeline = timeline
        if timeline:
            self._timeline.selection.connect('selection-changed', self._selectionChangedCb)

    timeline = property(_getTimeline, _setTimeline)
