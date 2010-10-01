#!/usr/bin/env python
# -*- Mode: Python -*-
# vi:si:et:sw=4:sts=4:ts=4

# (c) 2010 Luis de Bethencourt <luis@debethencourt.com>
# (c) 2010 PiTiVi community <someone@pitivi.org>
# Licensed under LGPL
#
# PiTiVi project file demuxer element for gstreamer.

import gobject
gobject.threads_init()
import pygst
pygst.require('0.10')
import gst
import sys
import os
from StringIO import StringIO

from pitivi.formatters.etree import ElementTreeFormatter
from pitivi.factories.timeline import TimelineSourceFactory

class PitiviProject(gst.Bin):
    __gstdetails__ = ('pitivi','Demuxer', \
                      'Pitivi Project file reader', 'Luis de Bethencourt')

    __gproperties__ = {
        'mode' : (gobject.TYPE_STRING, 'mode',
                  'what src pads are needed',
                  'normal',
                  gobject.PARAM_WRITABLE)}

    __gsttemplates__ = (
        gst.PadTemplate ("sink",
                         gst.PAD_SINK,
                         gst.PAD_ALWAYS,
                         gst.Caps('application/pitivi')),

        gst.PadTemplate ("video",
                         gst.PAD_SRC,
                         gst.PAD_SOMETIMES,
                         gst.Caps('video/x-raw-yuv')),
        gst.PadTemplate ("audio",
                         gst.PAD_SRC,
                         gst.PAD_SOMETIMES,
                         gst.Caps('audio/x-raw-int'))
        )

    def __init__(self):
        gst.Element.__init__(self)
        self.set_name('pitivi')
        self.mode = 'normal'

        # Creating sinkpad
        self.sinkpad = gst.Pad(self.__gsttemplates__[0])
        self.sinkpad.set_chain_function(self.chainfunc)
        self.sinkpad.set_event_function(self.eventfunc)
        self.add_pad(self.sinkpad)

        # Creating srcpad
        self.srcpad_video = gst.Pad(self.__gsttemplates__[1])
        self.srcpad_audio = gst.Pad(self.__gsttemplates__[2])

        self.file = StringIO()
        self.pads_added = 0

    # Sink pad functions
    def chainfunc(self, pad, buffer):
        outbuf = buffer.copy_on_write()
        self.file.write(outbuf)
        return gst.FLOW_OK

    def eventfunc(self, pad, event):
        self.info("%s sink event func: %r" % (pad, event.type))
        if event.type == gst.EVENT_EOS:
            self.file.seek(0)
            self.pitiviBin()
        else:
            self.srcpad_video.push_event(event)
            return self.srcpad_audio.push_event(event)

    # Timeline Bin creation
    def pitiviBin(self):
        formatter = ElementTreeFormatter(None)
        if not formatter:
            print "Not a valid project"

        self.file.seek(0)
        formatter.connect("new-project-loaded", self.newProjectLoadedCb)
        formatter.loadProjectFromFileObject(self.file)

    def newProjectLoadedCb(self, formatter, project):
        self.info("project loaded")
        timeline = project.timeline

        self.info("pitivi mode: " + self.mode)
        self.bin = project.factory.bin
        self.add(self.bin)
        self.bin.connect("pad-added", self.binPadsAddedCb)
        self.bin.sync_state_with_parent()

    def binPadsAddedCb(self, dbin, pad):
        caps = pad.get_caps()[0].get_name()
        name = pad.get_name()

        ghostpad = gst.GhostPad(name, self.bin.get_pad(name))

        if self.mode == "normal":
            ghostpad.activate_push(True)
            self.add_pad(ghostpad)

            self.info("pads added: " + caps)
            self.pads_added += 1
            if self.pads_added == 2:
                self.no_more_pads()

        # self.mode value is 'video' or 'audio'
        else:
            if caps.startswith(self.mode):
                ghostpad.activate_push(True)
                self.add_pad(ghostpad)

                self.no_more_pads()
                self.info("pads added: " + caps)
            else:
                ghostpad.set_blocked(True)

    def do_get_property(self, property):
        if property.name == 'mode':
            return self.mode
        else:
            raise AttributeError, 'unknown property %s' % property.name

    def do_set_property(self, property, value):
        if not value == 'normal':
            if (not value == 'video') and (not value == 'audio'):
                raise AttributeError, 'wrong mode value %s' % value

        if property.name == 'mode':
            self.mode = value
        else:
            raise AttributeError, 'unknown property %s' % property.name


def xptv_type_func(typefind, data1, data2):
    header = typefind.peek(0, 7)
    if header == '<pitivi':
        print 'PiTiVi file'
        typefind.suggest(gst.TYPE_FIND_MAXIMUM, gst.Caps('application/pitivi'))

# Register the element into this process' registry.
gobject.type_register(PitiviProject)
gst.element_register(PitiviProject, 'pitivi', gst.RANK_PRIMARY)
gst.type_find_register('application/pitivi', gst.RANK_PRIMARY, \
    xptv_type_func, ['xptv'], gst.Caps('application/pitivi'), None, None)

# Register the element factory.
__gstelementfactory__ = (
    "pitivi",
    gst.RANK_MARGINAL,
    PitiviProject
)


# Code to test the PitiviProject class
#
class Main:
    def __init__(self, args):
        if len(args) != 2:
            print 'Usage: %s inputfile' % (args[0])
            return -1
        self.location = args[1]
        gobject.threads_init ()

    def pipeline(self):
        self.pipeline = gst.Pipeline("pipeline")
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect ('message', self.bus_handler)

        filesrc = gst.element_factory_make("filesrc", "filesrc")
        filesrc.set_property('location', self.location)
        self.pipeline.add(filesrc)

        self.xptv = gst.element_factory_make("pitivi", "pitivi")
        self.xptv.set_property('mode', 'video')
#        Three modes are available for the pitivi element:
#            normal - normal output with audio and video streams.
#            video - the element will only output the video stream.
#            audio - the element will only output the audio stream.
        self.pipeline.add(self.xptv)
        self.xptv.connect('pad-added', self.OnPadAdded)
        filesrc.link(self.xptv)

        self.colorspace = \
            gst.element_factory_make("ffmpegcolorspace", "ffmpegcolorspace")
        self.pipeline.add(self.colorspace)

        self.vsink = gst.element_factory_make("xvimagesink", "xvimagesink")
        self.pipeline.add(self.vsink)
        self.colorspace.link(self.vsink)

#        Optionally, adding an audiosink to the pipeline will also work.
#        In that case the self.xptv mode should be set to "normal".
#        self.asink = gst.element_factory_make("autoaudiosink", "autoaudiosink")
#        self.pipeline.add(self.asink)

        self.pipeline.set_state(gst.STATE_PLAYING)

        gobject.MainLoop().run()

    def bus_handler(self, unused_bus, message):
        return gst.BUS_PASS

    def OnPadAdded(self, element, pad):
        caps = pad.props.caps or pad.get_caps()
        if caps[0].get_name().startswith("video"):
            pad.link(self.colorspace.get_pad("sink"))
#        elif caps[0].get_name().startswith("audio"):
#            pad.link(self.asink.get_pad("sink"))

    def playBin(self):
        self.pipeline = gst.parse_launch('playbin2 uri=file://%s' \
                                         % self.location)
        self.pipeline.set_state(gst.STATE_PLAYING)

if __name__ == '__main__':
    m = Main(sys.argv)
    m.pipeline()
#    m.playBin()
    gobject.MainLoop().run()
