"""abstract synthesis super-class."""
import abc
import warnings
import torch
from typing import Union, List


class Synthesis(metaclass=abc.ABCMeta):
    r"""Abstract super-class for synthesis methods.

    All synthesis methods share a variety of similarities and thus need
    to have similar methods. Some of these can be implemented here and
    simply inherited, some of them will need to be different for each
    sub-class and thus are marked as abstract methods here

    """

    @abc.abstractmethod
    def synthesize(self):
        r"""Synthesize something."""
        pass

    def save(self, file_path: str, attrs: Union[List[str], None] = None):
        r"""Save all relevant (non-model) variables in .pt file.

        If you leave attrs as None, we grab vars(self) and exclude 'model'.
        This is probably correct, but the option is provided to override it
        just in case

        Parameters
        ----------
        file_path : str
            The path to save the synthesis object to
        attrs : list or None, optional
            List of strs containing the names of the attributes of this
            object to save. See above for behavior if attrs is None.

        """
        if attrs is None:
            # this copies the attributes dict so we don't actually remove the
            # model attribute in the next line
            attrs = {k: v for k, v in vars(self).items()}
            attrs.pop('model', None)

        save_dict = {}
        for k in attrs:
            if k == 'model':
                warnings.warn("Models can be quite large and they don't change"
                              " over synthesis. Please be sure that you "
                              "actually want to save the model.")
            attr = getattr(self, k)
            # detaching the tensors avoids some headaches like the
            # tensors having extra hooks or the like
            if isinstance(attr, torch.Tensor):
                attr = attr.detach()
            save_dict[k] = attr
        torch.save(save_dict, file_path)

    def load(self, file_path: str,
             map_location: Union[str, None] = None,
             check_attributes: List[str] = [],
             check_loss_functions: List[str] = [],
             **pickle_load_args):
        r"""Load all relevant attributes from a .pt file.

        This should be called by an initialized ``Synthesis`` object -- we will
        ensure that the attributes in the ``check_attributes`` arg all match in
        the current and loaded object.

        Note this operates in place and so doesn't return anything.

        Parameters
        ----------
        file_path :
            The path to load the synthesis object from
        map_location :
            map_location argument to pass to ``torch.load``. If you save
            stuff that was being run on a GPU and are loading onto a
            CPU, you'll need this to make sure everything lines up
            properly. This should be structured like the str you would
            pass to ``torch.device``
        check_attributes :
            List of strings we ensure are identical in the current
            ``Synthesis`` object and the loaded one. Checking the model is
            generally not recommended, since it can be hard to do (checking
            callable objects is hard in Python) -- instead, checking the
            ``base_representation`` should ensure the model hasn't functinoally
            changed.
        check_loss_functions :
            Names of attributes that are loss functions and so must be checked
            specially -- loss functions are callables, and it's very difficult
            to check python callables for equality so, to get around that, we
            instead call the two versions on the same pair of tensors,
            and compare the outputs.

        pickle_load_args :
            any additional kwargs will be added to ``pickle_module.load`` via
            ``torch.load``, see that function's docstring for details.

        """
        tmp_dict = torch.load(file_path,
                              map_location=map_location,
                              **pickle_load_args)
        if map_location is not None:
            device = map_location
        else:
            for v in tmp_dict.values():
                if isinstance(v, torch.Tensor):
                    device = v.device
                    break
        for k in check_attributes:
            if not hasattr(self, k):
                raise Exception("All values of `check_attributes` should be "
                                "attributes set at initialization, but got "
                                f"attr {k}!")
            if isinstance(getattr(self, k), torch.Tensor):
                # there are two ways this can fail -- the first is if they're
                # the same shape but different values and the second (in the
                # except block) are if they're different shapes.
                try:
                    if not torch.allclose(getattr(self, k).to(tmp_dict[k].device),
                                          tmp_dict[k], rtol=5e-2):
                        raise Exception(f"Saved and initialized {k} are "
                                        f"different! Initialized: {getattr(self, k)}"
                                        f", Saved: {tmp_dict[k]}, difference: "
                                        f"{getattr(self, k) - tmp_dict[k]}")
                except RuntimeError:
                    raise Exception(f"Attribute {k} have different shapes in"
                                    " saved and initialized versions! Initialized"
                                    f": {getattr(self, k).shape}, Saved: "
                                    f"{tmp_dict[k].shape}")
            else:
                if getattr(self, k) != tmp_dict[k]:
                    raise Exception(f"Saved and initialized {k} are different!"
                                    f" Self: {getattr(self, k)}, "
                                    f"Saved: {tmp_dict[k]}")
        for k in check_loss_functions:
            # this way, we know it's the right shape
            tensor_a, tensor_b = torch.rand(2, *self._signal_shape).to(device)
            saved_loss = tmp_dict[k](tensor_a, tensor_b)
            init_loss = getattr(self, k)(tensor_a, tensor_b)
            if not torch.allclose(saved_loss, init_loss, rtol=1e-2):
                raise Exception(f"Saved and initialized {k} are "
                                "different! On two random tensors: "
                                f"Initialized: {init_loss}, Saved: "
                                f"{saved_loss}, difference: "
                                f"{init_loss-saved_loss}")
        for k, v in tmp_dict.items():
            setattr(self, k, v)

    @abc.abstractmethod
    def to(self, *args, attrs: List[str] = [], **kwargs):
        r"""Moves and/or casts the parameters and buffers.
        Similar to ``save``, this is an abstract method only because you
        need to define the attributes to call to on.
        
        This can be called as
        .. function:: to(device=None, dtype=None, non_blocking=False)
        .. function:: to(dtype, non_blocking=False)
        .. function:: to(tensor, non_blocking=False)
        Its signature is similar to :meth:`torch.Tensor.to`, but only accepts
        floating point desired :attr:`dtype` s. In addition, this method will
        only cast the floating point parameters and buffers to :attr:`dtype`
        (if given). The integral parameters and buffers will be moved
        :attr:`device`, if that is given, but with dtypes unchanged. When
        :attr:`non_blocking` is set, it tries to convert/move asynchronously
        with respect to the host if possible, e.g., moving CPU Tensors with
        pinned memory to CUDA devices. When calling this method to move tensors
        to a CUDA device, items in ``attrs`` that start with "saved_" will not
        be moved.
        .. note::
            This method modifies the module in-place.
        Args:
            device (:class:`torch.device`): the desired device of the parameters
                and buffers in this module
            dtype (:class:`torch.dtype`): the desired floating point type of
                the floating point parameters and buffers in this module
            tensor (torch.Tensor): Tensor whose dtype and device are the desired
                dtype and device for all parameters and buffers in this module
            attrs (:class:`list`): list of strs containing the attributes of
                this object to move to the specified device/dtype
        Returns:
            Module: self
        """
        try:
            self.model = self.model.to(*args, **kwargs)
        except AttributeError:
            warnings.warn("model has no `to` method, so we leave it as is...")

        device, dtype, non_blocking, memory_format = torch._C._nn._parse_to(*args, **kwargs)

        def move(a, k):
            move_device = None if k.startswith("saved_") else device
            if memory_format is not None and a.dim() == 4:
                return a.to(move_device, dtype, non_blocking,
                            memory_format=memory_format)
            else:
                return a.to(move_device, dtype, non_blocking)

        for k in attrs:
            if hasattr(self, k):
                attr = getattr(self, k)
                if isinstance(attr, torch.Tensor):
                    attr = move(attr, k)
                    if isinstance(getattr(self, k), torch.nn.Parameter):
                        attr = torch.nn.Parameter(attr)
                    setattr(self, k, attr)
                elif isinstance(attr, list):
                    setattr(self, k, [move(a, k) for a in attr])
        return self
