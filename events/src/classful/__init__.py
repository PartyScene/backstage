import typing
import inspect
import functools


from quart import Quart, Blueprint

DEFAULT_OPTIONS = {
    "rule": None,
    "options": None,
    "methods": ["GET"],
}
INSTACE_TYPE = typing.Union[Quart, Blueprint]


def route(rule: str, **options: typing.Dict) -> typing.Callable:
    """A decorator that registers a route
    in a cached place, so it can be lazy-loaded.
    """

    def decorator(func) -> typing.Callable:
        if hasattr(func, "_classful") is False:
            setattr(func, "_classful", {})

        if options is None:
            locals()["options"] = DEFAULT_OPTIONS

        func._classful = {"rule": rule, "options": options}
        return func

    return decorator


def request_hook(prefix: str) -> typing.Callable:
    """A decorator that registers a request hook
    in a cached place, so it can be lazy-loaded.
    """
    allowed_prefixes = [
        "before_request",
        "after_request",
        "before_app_serving",
        "after_app_serving",
        "before_app_request",
        "after_app_request",
        "before_websocket",
        "after_websocket",
    ]

    if prefix not in allowed_prefixes:
        raise ValueError("Invalid request hook.")

    def decorator(func) -> typing.Callable:
        if hasattr(func, "_classful") is False:
            setattr(func, "_classful", {})

        options = DEFAULT_OPTIONS
        options["hook"] = prefix

        func._classful = options
        return func

    return decorator


class QuartClassful:
    """A class to wrap all the routes, so they can
    be used in a Quart or Blueprint instance.
    """

    routes: typing.List[typing.Tuple[str, typing.Callable]] = []
    cls_functions: typing.List[str] = ["register"]

    @staticmethod
    def get_intersting_members(
        cls: typing.Type,
    ) -> typing.List[typing.Tuple[str, typing.Callable]]:
        """Get all the interesting members of a class."""
        check_lambda = lambda x: inspect.isfunction(x) or inspect.ismethod(x)

        base_members = inspect.getmembers(QuartClassful, check_lambda)

        intersting_members = []
        all_members = inspect.getmembers(cls, check_lambda)
        for name, member in all_members:
            if (name, member) not in base_members:
                intersting_members.append((name, member))

        return intersting_members

    def register_rule(
        self, instance: "INSTACE_TYPE", member: typing.Callable, func: typing.Callable
    ) -> None:
        """Register a rule and its method."""

        if hasattr(member, "_classful") is False:
            return

        rule = member._classful.get("rule")
        options = member._classful.get("options", {})
        methods = options.get("methods", ["GET"])
        instance.add_url_rule(rule, view_func=func, methods=methods)

    def register_hook(
        self, instance: "INSTACE_TYPE", member: typing.Callable, func: typing.Callable
    ) -> None:
        """Register a hook and its method."""

        if hasattr(member, "_classful") is False:
            return

        if "hook" not in member._classful:
            return

        hook = member._classful.get("hook")
        call_func = getattr(instance, hook, None)
        if call_func is not None:
            call_func(func)

    @classmethod
    def register(cls, instance: "INSTACE_TYPE", *args, **kwarg) -> None:
        """Register all the routes and their methods."""

        if cls is QuartClassful:
            raise TypeError("Cannot register the base class.")

        self = cls(*args, **kwarg)
        members = cls.get_intersting_members(cls)

        for name, member in members:
            if name not in cls.cls_functions:
                pass

            func = functools.partial(member, self)
            func.__name__ = member.__name__

            if hasattr(member, "_classful"):
                args = (instance, member, func)
                if "hook" in member._classful:
                    self.register_hook(*args)
                if "hook" not in member._classful:
                    self.register_rule(*args)
