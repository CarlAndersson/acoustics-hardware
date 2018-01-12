import numpy as np
import threading
import logging

from . import core
from .utils import LevelDetector

logger = logging.getLogger(__name__)


class RMSTrigger(core.Trigger):
    def __init__(self, *, level, channel, fs, action=None, region='Above', **kwargs):
        Trigger.__init__(self, action=action)
        self.level_detector = LevelDetector(channel=channel, fs=fs, **kwargs)
        self.region = region
        self.trigger_level = level

    # TODO: If the loop is not fast enough there are a few options.
    # If we drop the possibility for separate attack and release times, the level detector is
    # just a IIR filter, so we could use scipy.signal.lfilter([1, (1-alpha)], alpha, input_levels)
    # It should also be possible (I think) to write the level detector using Faust, and just drop in the
    # wrapped Faust code here. If I manage to get that working it could also be used for all other crazy
    # filters we might want to use.
    def test(self, frame):
        # logger.debug('Testing in RMS trigger')
        levels = self.level_detector(frame)
        return any(self._sign * levels > self.trigger_level * self._sign)

    # def __call__(self, frame):
    #     # trigger_on = self._event.is_set()
    #     # logger.debug('RMSTrigger called!')
    #     levels = self.level_detector(frame)

    #     # This will switch the state if the trigger level is passed at least once
    #     # It should be more robust for transients: If there is a transient that turns on the triggering
    #     # we do not care if the level dropped afterwards.
    #     if any(self._kind_sign * levels > self.trigger_level * self._kind_sign):
    #         logger.debug('Trigger active')
    #         [action() for action in self.active_actions]
    #     else:
    #         [action() for action in self.deactive_actions]

    @property
    def region(self):
        if self._sign == 1:
            return 'Above'
        else:
            return 'Below'

    @region.setter
    def region(self, value):
        if value.lower() == 'above':
            self._sign = 1
        elif value.lower() == 'below':
            self._sign = -1
        else:
            raise ValueError('{} not a valid regoin for RMS trigger.'.format(value))


class PeakTrigger(core.Trigger):
    def __init__(self, *, level, channel, action, region='Above'):
        Trigger.__init__(self, action=action)
        # self.action = action
        self.region = region
        self.trigger_level = level
        self.channel = channel

    def test(self, frame):
        # logger.debug('Testing in Peak triggger')
        levels = np.abs(frame[self.channel])
        return any(self._sign * levels > self.trigger_level * self._sign)

    # def __call__(self, frame):
    #     levels = np.abs(frame[channel])
    #     if any(self._sign * levels > self.trigger_level * self._sign):
    #         self.action()

    @property
    def region(self):
        if self._sign == 1:
            return 'Above'
        else:
            return 'Below'

    @region.setter
    def region(self, value):
        if value.lower() == 'above':
            self._sign = 1
        elif value.lower() == 'below':
            self._sign = -1
        else:
            raise ValueError('{} not a valid region for peak trigger.'.format(value))


class DelayedAction:
    def __init__(self, *, action, time):
        self.action = action
        self.time = time
        # self.timer = Timer(interval=time, function=action)

    def __call__(self):
        timer = threading.Timer(interval=self.time, function=self.action)
        timer.start()
        # self.timer.start()