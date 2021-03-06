import numpy as np
import threading
import logging
import warnings

from . import processors

logger = logging.getLogger(__name__)


class Trigger:
    """Base class for Trigger implementation.

    A Trigger is an object that performs a test on all input data from a
    Device, regardless if the input is set as active or not. If the test
    evaluates to ``True`` the trigger will perform a set of actions,
    e.g. activate the input of a Device.

    Arguments:
        actions (callable or list of callables): The actions that will be
            called each time the test evaluates to ``True``.
        false_actions (callable or list of callables): The actions that will be
            called each time the test evaluates to ``False``.
        auto_deactivate (`bool`): Sets if the trigger deactivates itself when
            the test is ``True``. Useful to only trigger once, dafault ``True``.
        use_calibrations (`bool`): Sets if calibration values from the Device
            should be used for the test, default ``True``.
    Attributes:
        active (`~threading.Event`): Controls if the trigger is active or not.
            A deactivated trigger will still test (e.g. to track levels), but
            not take action. Triggers start of as active unless manually deactivated.
    """
    def __init__(self, action=None, false_action=None, auto_deactivate=True,
                 use_calibrations=True, device=None, align_device=None, side='input'):
        self.side = side
        self.device = device
        # self.active = multiprocessing.Event()
        self.active = threading.Event()
        self.active.set()

        self.actions = []
        if action is not None:
            try:
                self.actions.extend(action)
            except TypeError:
                self.actions.append(action)

        self.false_actions = []
        if false_action is not None:
            try:
                self.false_actions.extend(false_action)
            except TypeError:
                self.false_actions.append(false_action)

        self.alignment = None
        self.align_devices = []
        if align_device is not None:
            try:
                self.align_devices.extend(align_device)
            except TypeError:
                self.align_devices.append(align_device)

        self.auto_deactivate = auto_deactivate
        self.use_calibrations = use_calibrations

    def __call__(self, frame):
        """Manages testing and actions."""
        # We need to perform the test event if the triggering is disabled
        # Some triggers (RMSTrigger) needs to update their state continuously to work as intended
        # If e.g. RMSTrigger cannot update the level with the triggering disabled, it will always
        # start form zero
        test = self.test(frame * self.calibrations)
        if self.active.is_set():
            # logger.debug('Testing in {}'.format(self.__class__.__name__))
            if any(test):
                self.alignment = np.where(test)[0][0] / self.device.fs
                test = True
            else:
                self.alignment = None
                test = False
            if test:
                [action() for action in self.actions]
                for dev in self.align_devices:
                    dev._trigger_alignment = self.alignment
            else:
                [action() for action in self.false_actions]

    def test(self, frame):
        """Performs test.

        The trigger conditions should be implemented here.

        Arguments:
            frame (`numpy.ndarray`): The current input frame to test.
        Returns:
            `bool`: ``True`` -> do ``actions``, ``False`` -> do ``false_actions``
        """
        raise NotImplementedError('Required method `test` is not implemented in {}'.format(self.__class__.__name__))

    def reset(self):
        """Resets the trigger state."""
        self.active.set()

    def setup(self):
        """Configures trigger state."""
        if self.side == 'input':
            if self.use_calibrations:
                calibrations = self.device.calibrations
            else:
                calibrations = np.ones(len(self.device.inputs))
        else:
            calibrations = np.ones(len(self.device.outputs))
        self.calibrations = calibrations[:, np.newaxis]

    @property
    def auto_deactivate(self):
        return self.active.clear in self.actions

    @auto_deactivate.setter
    def auto_deactivate(self, value):
        if value and not self.auto_deactivate:
            self.actions.insert(0, self.active.clear)
        elif self.auto_deactivate and not value:
            self.actions.remove(self.active.clear)

    @property
    def device(self):
        try:
            return self._device
        except AttributeError:
            return None

    @device.setter
    def device(self, dev):
        if self.device is not None:
            # Unregister from the previous device
            if self.device.initialized:
                self.reset()
            if self.side == 'input':
                self.device._Device__triggers.remove(self)
            elif self.side == 'output':
                self.device._Device__output_triggers.remove(self)
        self._device = dev
        if self.device is not None:
            # Register to the new device
            if self.side == 'input':
                self.device._Device__triggers.append(self)
            elif self.side == 'output':
                self.device._Device__output_triggers.append(self)
                if self.device.initialized:
                    self.setup()


class RMSTrigger(Trigger):
    """RMS level trigger.

    Triggers actions based on a detected root-mean-square level.

    Arguments:
        level (`float`): The level at which to trigger.
        channel (`int`): The index of the channel on which to trigger.
        region (``'Above'`` or ``'Below'``, optional): Defines if the triggering
            happens when the detected level rises above or falls below the set
            level, default ``'Above'``.
        level_detector_args (`dict`, optional): Passed as keyword arguments to
            the internal `~.processors.LevelDetector`.
        **kwargs: Extra keyword arguments passed to `Trigger`.

    Todo:
        Rename region to slope?
    """
    def __init__(self, level, channel, region='Above', level_detector_args=None, **kwargs):
        super().__init__(**kwargs)
        self.channel = channel
        # self.level_detector = LevelDetector(channel=channel, fs=fs, **kwargs)
        self.region = region
        self.trigger_level = level
        self.level_detector_args = level_detector_args if level_detector_args is not None else {}

    def setup(self):
        super().setup()
        self.level_detector = processors.LevelDetector(channel=self.channel, device=self.device, **self.level_detector_args)

    def test(self, frame):
        # logger.debug('Testing in RMS trigger')
        levels = self.level_detector(frame)
        return self._sign * levels >= self.trigger_level * self._sign
        # meets_criteria = self._sign * levels > self.trigger_level * self._sign
        # if any(meets_criteria):
            # self.trigger_alignment = np.where(meets_criteria)[0][0]
            # return True
        # else:
            # return False

    def reset(self):
        super().reset()
        self.level_detector.reset()

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
            raise ValueError('{} not a valid region for RMS trigger.'.format(value))


class PeakTrigger(Trigger):
    """Peak level trigger.

    Triggers actions based on detected peak level.

    Arguments:
        level (`float`): The level at which to trigger.
        channel (`int`): The index of the channel on which to trigger.
        region (``'Above'`` or ``'Below'``, optional): Defines if the triggering
            happens when the detected level rises above or falls below the set
            level, default ``'Above'``.
        **kwargs: Extra keyword arguments passed to `Trigger`.

    Todo:
        Rename region to slope?
    """
    def __init__(self, level, channel, region='Above', **kwargs):
        super().__init__(**kwargs)
        self.region = region
        self.trigger_level = level
        self.channel = channel

    def test(self, frame):
        # logger.debug('Testing in Peak triggger')
        levels = np.abs(frame[self.channel])
        return self._sign * levels >= self.trigger_level * self._sign
        # return any(self._sign * levels > self.trigger_level * self._sign)

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
    """Delays an action.

    When called, an instance of this class will excecute a specified action
    after a set delay. This can be useful to create timed measurements or
    pauses in a longer sequence.

    Arguments:
        action (callable): Any callable action. This can be a callable class,
            a user defined funciton, or a method of another class.
            If several actions are required, pass an iterable of callables.
        time (`float`): The delay time, in seconds.
    """

    def __init__(self, action, time):
        actions = []
        try:
            actions.extend(action)
        except TypeError:
            actions.append(action)
        self.actions = actions
        self.time = time
        # self.timer = Timer(interval=time, function=action)

    def __call__(self):
        timer = threading.Timer(interval=self.time, function=lambda: [action() for action in self.actions])
        timer.start()
        # self.timer.start()
