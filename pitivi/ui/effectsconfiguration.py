#
#       ui/effectsconfiguration.py
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
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.

import gtk
import gobject

from pitivi.pipeline import PipelineError
from pitivi.ui.gstwidget import GstElementSettingsWidget

PROPS_TO_IGNORE = ['name', 'qos']

class EffectsPropertiesHandling:
    def __init__(self, action_log):
        self.cache_dict = {}
        self.pipeline = None
        self._current_effect_setting_ui = None
        self._current_element_values = {}
        self.action_log = action_log

    def getEffectConfigurationUI(self, effect):
        """
            Permit to get a configuration GUI for the effect
            @param effect: The effect for which whe want the configuration UI
            @type effect: C{gst.Element}
        """
        if effect not in self.cache_dict:
            #Here we should handle special effects configuration UI
            if 'aspectratiocrop' in effect.get_name():
                effect_set_ui = AspectRatioUi()
            else:
                effect_set_ui = GstElementSettingsWidget()
                effect_set_ui.setElement(effect, ignore=PROPS_TO_IGNORE,
                                                   default_btn=True, use_element_props=True)
                nb_rows = effect_set_ui.get_children()[0].get_property('n-rows')
                if nb_rows > 2:
                    effect_configuration_ui = gtk.ScrolledWindow()
                    effect_configuration_ui.add_with_viewport(effect_set_ui)
                    self.cache_dict[effect] = effect_configuration_ui
                else:
                    self.cache_dict[effect] = effect_set_ui
                self._connectAllWidgetCbs(effect_set_ui, effect)

        effect_set_ui = self._getUiToSetEffect(effect)

        self._current_effect_setting_ui = effect_set_ui
        element = self._current_effect_setting_ui.element
        for prop in gobject.list_properties(element):
            self._current_element_values[prop.name] = element.get_property(prop.name)

        return self.cache_dict[effect]

    def cleanCache(self, effect):
        if self.cache_dict.has_key(effect):
            conf_ui = self.effect_props_handling.cache_dict.get(effect)
            self.cache_dict.pop(effect)
            return conf_ui

    def _getUiToSetEffect(self, effect):
        """ Permit to get the widget to set the effect and not its container """
        if type(self.cache_dict[effect]) is gtk.ScrolledWindow:
            effect_set_ui = self.cache_dict[effect].get_children()[0].get_children()[0]
        else:
            effect_set_ui = self.cache_dict[effect]

        return effect_set_ui

    def _flushSeekVideo(self):
        self.pipeline.pause()
        if self.pipeline is not None:
            try:
                self.pipeline.seekRelative(0)
            except PipelineError:
                pass

    def _connectAllWidgetCbs(self, effect_configuration_ui, effect):
        for prop, widget in effect_configuration_ui.properties.iteritems():
            widget.connectValueChanged(self._onValueChangedCb, widget, prop)

    def _onSetDefaultCb(self, widget, dynamic):
        dynamic.setWidgetToDefault()

    def _onValueChangedCb(self, widget, dynamic, prop):
        value = dynamic.getWidgetValue()
        if value != self._current_element_values.get(prop.name):
            self.action_log.begin("Effect property change")
            self._current_effect_setting_ui.element.set_property(prop.name, value)
            self.action_log.commit()
            self._current_element_values[prop.name] = value

        self._flushSeekVideo()


class AspectRatioUi(GstElementSettingsWidget):
    """
        UI to configure AspectRatio effects
    """
    def __init__(self):
        GstElementSettingsWidget.__init__(self)

