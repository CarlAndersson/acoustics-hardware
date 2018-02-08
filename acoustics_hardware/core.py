import queue
import threading
import multiprocessing
import collections


class Device:
    """
    Top level abstract Device class used for inheritance to implement specific hardware.
    Required methods to implement:
    - `_hardware_run`: Main method used to run the hardware

    Optional methods to override:
    - `_hardware_stop`: Use to stop the hardware
    - `_hardware_reset`: Use to reset the hardware/python object to a startable state

    See the documentation of these for more information.

    """
    _trigger_timeout = 1
    _q_timeout = 1
    _hardware_timeout = 1
    _attr_timeout = 0.05
    _attr_response_timeout = 1

    def __init__(self):
        self.input_active = multiprocessing.Event()
        self.output_active = multiprocessing.Event()
        self._hardware_output_Q = multiprocessing.Queue()

        # self._hardware_input_Q = queue.Queue()
        # self._hardware_stop_event = threading.Event()
        # self.__triggered_q = queue.Queue()
        # self.__trigger_stop_event = threading.Event()
        # self.__q_stop_event = threading.Event()

        # self._hardware_input_Q = multiprocessing.Queue()
        # self._hardware_stop_event = multiprocessing.Event()
        # self.__triggered_q = multiprocessing.Queue()
        # self.__q_stop_event = multiprocessing.Event()
        # self.__trigger_stop_event = multiprocessing.Event()
        self.__attr_request_Q = multiprocessing.Queue()
        self.__attr_response_Q = multiprocessing.Queue()

        self.__triggers = []
        self.__Qs = []

        self.__process_stop_event = multiprocessing.Event()
        self.__process = multiprocessing.Process()

    def start(self):
        # TODO: Documentation
        self.__process = multiprocessing.Process(target=self._Device__process_target)
        self.__process.start()

    def stop(self):
        # TODO: Documentation
        self.__process_stop_event.set()
        # self.__process.join(timeout=10)
        # TODO: We will not wait for the process now, since it will not finish if there are
        # items left in the Q.

    def _hardware_run(self):
        '''
        This is the primary method in which hardware interfacing should be implemented.
        There are two Qs, two required events, and two default controll events.
            `_hardware_input_Q`: The Q where read input data should go
            `_hardware_output_Q`: The Q where the output data to write is stored
            `input_active`: The event which toggles if data should be placed in the input Q
            `output_active`; The event whoch toggles if data should be read from the output Q
            `_hardware_stop_event`: Tells the hardware thread to stop, see `_hardware_stop` and `_hardware_reset`
        '''
        raise NotImplementedError('Required method `_hardware_run` not implemented in {}'.format(self.__class__.__name__))

    def _hardware_stop(self):
        '''
        This is the primary method used for stopping the hardware.
        It is reccomended to do this using Events inside the _hardware_run method.

        Default implementation:
            self._hardware_stop_event.set()
        '''
        self._hardware_stop_event.set()

    def _hardware_reset(self):
        '''
        This method works in combination with `_hardware_setup` to put the hardware back to a state
        where it can be started again.
        '''
        pass

    def flush(self):
        '''
        Used to flush all Qs so that processes can terminate.
        THIS WILL DELETE DATA which is still in the Qs
        '''
        for Q in self.__Qs:
            while True:
                try:
                    Q.get(timeout=0.1)
                except queue.Empty:
                    break
        while True:
            try:
                self.output_Q.get(timeout=0.1)
            except queue.Empty:
                break

    def get_new_Q(self):
        if self.__process.is_alive():
            # TODO: Custom warning class
            raise UserWarning('It is not possible to register new Qs while the device is running. Stop the device and perform all setup before starting.')
        else:
            Q = multiprocessing.Queue()
            self.__Qs.append(Q)
            return Q

    def remove_Q(self, Q):
        if self.__process.is_alive():
            # TODO: Custom warning class
            raise UserWarning('It is not possible to remove Qs while the device is running. Stop the device and perform all setup before starting.')
        else:
            # TODO: What should happen if the Q is not in the list?
            self.__Qs.remove(Q)

    @property
    def output_Q(self):
        # TODO: Documentation
        # This only exists to have consistent naming conventions (_hardware_input_Q, _hardware_output_Q) for subclassing
        return self._hardware_output_Q

    def register_trigger(self, trigger):
        # TODO: Documentation
        if self.__process.is_alive():
            # TODO: Custom warning class
            raise UserWarning('It is not possible to register new triggers while the device is running. Stop the device and perform all setup before starting.')
        else:
            self.__triggers.append(trigger)

    def remove_trigger(self, trigger):
        # TODO: Documentation
        if self.__process.is_alive():
            # TODO: Custom warning class
            raise UserWarning('It is not possible to remove triggers while the device is running. Stop the device and perform all setup before starting.')
        else:
            self.__triggers.remove(trigger)

    def __reset(self):
        self.__process_stop_event.clear()
        self.__trigger_stop_event.clear()
        self.__q_stop_event.clear()
        self._hardware_reset()
        self._hardware_stop_event.clear()

    def _Device__process_target(self):
        # The explicit naming of this method is needed on windows for some stange reason.
        # If we rely on the automatic name wrangling for the process target, it will not be found in device subclasses.
        self._hardware_input_Q = queue.Queue()
        self._hardware_stop_event = threading.Event()
        self.__triggered_q = queue.Queue()
        self.__trigger_stop_event = threading.Event()
        self.__q_stop_event = threading.Event()
        # Start hardware in separate thread
        # Manage triggers in separate thread
        # Manage Qs in separate thread
        hardware_thread = threading.Thread(target=self._hardware_run)
        trigger_thread = threading.Thread(target=self.__trigger_target)
        q_thread = threading.Thread(target=self.__q_target)

        hardware_thread.start()
        trigger_thread.start()
        q_thread.start()

        self.__process_stop_event.wait()

        self._hardware_stop()
        hardware_thread.join()
        self.__trigger_stop_event.set()
        trigger_thread.join()
        self.__q_stop_event.set()
        q_thread.join()
        self.__reset()
        # TODO: We will not finish the process if there are items still in the Q,
        # the question is what we want to do about it?

    def __trigger_target(self):
        # TODO: Get buffer size depending on pre-trigger value
        data_buffer = collections.deque(maxlen=10)

        # TODO: Get trigger scaling if needed
        trigger_scaling = 1

        while not self.__trigger_stop_event.is_set():
            # Wait for a frame, if none has arrived within the set timeout, go back and check stop condition
            try:
                this_frame = self._hardware_input_Q.get(timeout=self._trigger_timeout)
            except queue.Empty:
                continue
            # Execute all triggering conditions
            for trig in self.__triggers:
                trig(this_frame * trigger_scaling)
            # Move the frame to the buffer
            data_buffer.append(this_frame)
            # If the trigger is active, move everything from the data buffer to the triggered Q
            if self.input_active.is_set():
                while len(data_buffer) > 0:
                    self.__triggered_q.put(data_buffer.popleft())

        # The hardware should have stopped by now, analyze all remaining frames.
        while True:
            try:
                this_frame = self._hardware_input_Q.get(timeout=self._trigger_timeout)
            except queue.Empty:
                break
            for trig in self.__triggers:
                trig(this_frame * trigger_scaling)
            data_buffer.append(this_frame)
            if self.input_active.is_set():
                while len(data_buffer) > 0:
                    self.__triggered_q.put(data_buffer.popleft())

    def __q_target(self):
        while not self.__q_stop_event.is_set():
            # Wait for a frame, if none has arrived within the set timeout, go back and check stop condition
            try:
                this_frame = self.__triggered_q.get(timeout=self._q_timeout)
            except queue.Empty:
                continue
            for Q in self.__Qs:
                # Copy the frame to all output Qs
                Q.put(this_frame)

        # The triggering should have stopped by now, move the remaining frames.
        while True:
            try:
                this_frame = self.__triggered_q.get(timeout=self._q_timeout)
            except queue.Empty:
                break
            for Q in self.__Qs:
                Q.put(this_frame)

    def _update_attrs(self):
        changed = False
        while True:
            try:
                item = self.__attr_request_Q.get(timeout=self._attr_timeout)
            except queue.Empty:
                # No more pending messages
                break
            if len(item) == 2:
                # We are setting from remote process
                setattr(self, *item)
                changed = True
            else:
                # We received a request for some property
                self.__attr_response_Q.put(getattr(self, item))
        return changed


class InterProcessAttr:
    def __init__(self, attr):
        self.attr = '_' + attr

    def __get__(self, obj, objtype):
        if obj._Device__process.is_alive() and obj._Device__process is not multiprocessing.current_process():
            # The process is running, and we are trying to access it from a another process
            obj._Device__attr_request_Q.put(self.attr)  # Create a request for the attribute
            val = obj._Device__attr_response_Q.get(timeout=obj._attr_response_timeout)  # Wait for the response
            setattr(obj, self.attr, val)  # Update the local attribute
            return val
        else:
            return getattr(obj, self.attr)

    def __set__(self, obj, val):
        setattr(obj, self.attr, val)
        if obj._Device__process.is_alive() and obj._Device__process is not multiprocessing.current_process():
            # The device subprocess has started, and we are setting it from another process
            obj._Device__attr_request_Q.put((self.attr, val))


class Trigger:
    # TODO: Documentation
    def __init__(self, action=None, false_action=None):
        self.active = multiprocessing.Event()
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

    def __call__(self, frame):
        # We need to perform the test event if the triggering is disabled
        # Some triggers (RMSTrigger) needs to update their state continiously to work as intended
        # If e.g. RMSTrigger cannot update the level with the triggering disabled, it will always
        # start form zero
        test = self.test(frame)
        if self.active.is_set():
            # logger.debug('Testing in {}'.format(self.__class__.__name__))
            if test:
                [action() for action in self.actions]
            else:
                [action() for action in self.false_actions]

    def test(self, frame):
        raise NotImplementedError('Required method `test` is not implemented in {}'.format(self.__class__.__name__))


class Printer(Device):
    def _hardware_run(self):
        # print(dir(self))
        while not self._hardware_stop_event.is_set():
            try:
                print(self._hardware_output_Q.get(timeout=1))
            except queue.Empty:
                continue
