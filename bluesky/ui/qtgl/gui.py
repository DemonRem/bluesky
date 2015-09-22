try:
    from PyQt4.QtCore import Qt, QEvent
    from PyQt4.QtGui import QColor, QApplication, QFileDialog
    from PyQt4.QtOpenGL import QGLFormat
    print('Using Qt4 for windows and widgets')
except ImportError:
    from PyQt5.QtCore import Qt, QEvent
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import QApplication, QFileDialog
    from PyQt5.QtOpenGL import QGLFormat
    print('Using Qt5 for windows and widgets')

# Local imports
from ..radarclick import radarclick
from mainwindow import MainWindow, Splash
from uievents import PanZoomEvent, ACDataEvent, StackTextEvent, PanZoomEventType, ACDataEventType, SimInfoEventType, StackTextEventType, ShowDialogEventType, DisplayFlagEventType
from radarwidget import RadarWidget
import autocomplete as ac


class Gui(QApplication):
    modes = ['Init', 'Operate', 'Hold', 'End']

    def __init__(self, navdb):
        super(Gui, self).__init__([])
        self.acdata = ACDataEvent()
        self.navdb = navdb
        self.radarwidget = []
        self.command_history = []
        self.history_pos = 0
        self.command_mem = ''
        self.simevent_target = 0
        # Register our custom pan/zoom event
        for etype in [PanZoomEventType, ACDataEventType, SimInfoEventType]:
            reg_etype = QEvent.registerEventType(etype)
            if reg_etype != etype:
                print('Warning: Registered event type differs from requested type id (%d != %d)' % (reg_etype, etype))

        self.prevmousepos = (0.0, 0.0)

        self.splash = Splash()
        self.splash.show()

        self.splash.showMessage('Constructing main window')
        self.processEvents()

        # Create the main window
        self.radarwidget = RadarWidget(navdb)
        self.win = MainWindow(self, self.radarwidget)

        # Check OpenGL capabilities
        if not QGLFormat.hasOpenGL():
            raise RuntimeError('No OpenGL support detected for this system!')

    def setSimEventTarget(self, obj):
        self.simevent_target = obj

    def start(self):
        self.win.show()
        self.splash.showMessage('Done!')
        self.processEvents()
        self.splash.finish(self.win)
        self.exec_()

    def notify(self, receiver, event):
        # Events from the simulation thread
        if receiver is self:
            if event.type() == PanZoomEventType:
                if event.panzoom_type() == PanZoomEvent.Zoom:
                    event.vorigin = self.radarwidget.pan

                # send the pan/zoom event to the radarwidget
                receiver = self.radarwidget

            elif event.type() == ACDataEventType:
                self.acdata = event
                self.radarwidget.update_aircraft_data(event)
                return True

            elif event.type() == SimInfoEventType:
                self.win.siminfoLabel.setText('<b>F</b> = %.2f Hz, <b>sim_dt</b> = %.2f, <b>sim_t</b> = %.1f, <b>n_aircraft</b> = %d, <b>mode</b> = %s'
                    % (event.sys_freq, event.simdt, event.simt, event.n_ac, self.modes[event.mode]))
                return True

            elif event.type() == StackTextEventType:
                self.win.stackText.setTextColor(QColor(0, 255, 0))
                self.win.stackText.insertHtml('<br>' + event.text)
                self.win.stackText.verticalScrollBar().setValue(self.win.stackText.verticalScrollBar().maximum())
                return True

            elif event.type() == ShowDialogEventType:
                if event.dialog_type == event.filedialog_type:
                    self.show_file_dialog()
                return True

            elif event.type() == DisplayFlagEventType:
                print 'toggle event received by gui'
                return True

        # Mouse/trackpad event handling for the Radar widget
        if receiver is self.radarwidget:

            if event.type() == QEvent.Wheel:
                # For mice we zoom with control/command and the scrolwheel
                if event.modifiers() & Qt.ControlModifier:
                    origin = (event.pos().x(), event.pos().y())
                    zoom   = 1.0
                    try:
                        if event.pixelDelta():
                            # High resolution scroll
                            zoom *= (1.0 + 0.01 * event.pixelDelta().y())
                        else:
                            # Low resolution scroll
                            zoom *= (1.0 + 0.001 * event.angleDelta().y())
                    except:
                        zoom *= (1.0 + 0.001 * event.delta())

                    return super(Gui, self).notify(self.radarwidget, PanZoomEvent(PanZoomEvent.Zoom, zoom, origin))
                # For touchpad scroll (2D) is used for panning
                else:
                    try:
                        pan = (0.01 * event.pixelDelta().y(), -0.01 * event.pixelDelta().x())
                        return super(Gui, self).notify(self.radarwidget, PanZoomEvent(PanZoomEvent.Pan, pan))
                    except:
                        pass
            # For touchpad, pinch gesture is used for zoom
            elif event.type() == QEvent.Gesture:
                origin = (0, 0)
                zoom   = 1.0
                for g in event.gestures():
                    if g.gestureType() == Qt.PinchGesture:
                        origin = (g.centerPoint().x(), g.centerPoint().y())
                        zoom  *= g.scaleFactor() / g.lastScaleFactor()

                return super(Gui, self).notify(self.radarwidget, PanZoomEvent(PanZoomEvent.Zoom, zoom, origin))

            elif event.type() == QEvent.MouseButtonPress:
                # For mice we pan with control/command and mouse movement. Mouse button press marks the beginning of a pan
                if event.modifiers() & Qt.ControlModifier:
                    self.prevmousepos = (event.x(), event.y())

                else:
                    latlon  = self.radarwidget.pixelCoordsToLatLon(event.x(), event.y())
                    cmdline = str(self.win.lineEdit.text())[2:]
                    tostack, todisplay = radarclick(cmdline, latlon[0], latlon[1], self.acdata, self.navdb)
                    if len(todisplay) > 0:
                        if todisplay[0] == '\n':
                            self.win.lineEdit.setText(">>")
                        self.win.lineEdit.insert(todisplay.strip())
                        if todisplay[-1] == '\n':
                            self.win.lineEdit.setText(">>")
                        if len(tostack) > 0:
                            self.stack(tostack)
                    event.accept()
                    return True

            elif event.type() == QEvent.MouseMove and event.modifiers() & Qt.ControlModifier and event.buttons() & Qt.LeftButton:
                pan = (0.003 * (event.y() - self.prevmousepos[1]), 0.003 * (self.prevmousepos[0] - event.x()))
                self.prevmousepos = (event.x(), event.y())
                return super(Gui, self).notify(self.radarwidget, PanZoomEvent(PanZoomEvent.Pan, pan))

        # Other events
        if event.type() == QEvent.KeyPress:
            linelength = len(self.win.lineEdit.text())
            if event.key() == Qt.Key_Backspace:
                if linelength > 2:
                    return super(Gui, self).notify(self.win.lineEdit, event)
            if event.key() == Qt.Key_Enter or event.key() == Qt.Key_Return:
                if self.win.lineEdit.text() != ">>":
                    # emit a signal with the command for the simulation thread
                    cmd = str(self.win.lineEdit.text())[2:]
                    self.command_history.append(cmd)
                    self.stack(cmd)

                    self.win.lineEdit.setText(">>")
                    self.win.lineEdit.setCursorPosition(2)
            elif event.key() == Qt.Key_Up:
                if self.history_pos == 0 and self.win.lineEdit.text() != ">>":
                    self.command_mem = self.win.lineEdit.text()[2:]
                if len(self.command_history) >= self.history_pos + 1:
                    self.history_pos += 1
                    self.win.lineEdit.setText('>>' + self.command_history[-self.history_pos])

            elif event.key() == Qt.Key_Down:
                if self.history_pos > 0:
                    self.history_pos -= 1
                    if self.history_pos == 0:
                        self.win.lineEdit.setText('>>' + self.command_mem)
                    else:
                        self.win.lineEdit.setText('>>' + self.command_history[-self.history_pos])

            elif event.key() == Qt.Key_Tab:
                if self.win.lineEdit.text() != ">>":
                    cmd = str(self.win.lineEdit.text())[2:]
                    if len(cmd) > 0:
                        newcmd, displaytext = ac.complete(cmd)
                        self.win.lineEdit.setText('>>' + newcmd)
                        if len(displaytext) > 0:
                            self.callback_stack_output(displaytext)

            else:
                self.win.lineEdit.insert(str(event.text()).upper())
            event.accept()
            return True

        else:
            # Call Base Class Method to Continue Normal Event Processing
            return super(Gui, self).notify(receiver, event)

    def stack(self, text):
        self.postEvent(self.simevent_target, StackTextEvent(text))

    def show_file_dialog(self):
        print 'here'
        response = QFileDialog.getOpenFileName(self.win, 'Open file', 'data/scenario', 'Scenario files (*.scn)')
        if type(response) is tuple:
            fname = response[0]
        else:
            fname = response
        if len(fname) > 0:
            self.stack('IC ' + str(fname))