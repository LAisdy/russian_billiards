"""Step 2 verification: russian_pyramid module skeleton.

Checks that:
- ``pooltool.ruleset.russian_pyramid`` imports cleanly (submodule + package attr)
- the four discipline classes exist, subclass Ruleset, and appear in __all__
- each class implements the 5 required methods with correct signatures
  (parameter names + resolved return annotations)
- every stub raises NotImplementedError when invoked
- instantiating a class surfaces the stub (Ruleset.__init__ calls
  initial_shot_constraints) as NotImplementedError
"""

import inspect
import sys
import typing

from pooltool.ruleset import russian_pyramid as mod
from pooltool.ruleset.datatypes import Ruleset, ShotConstraints, ShotInfo

EXPECTED_CLASSES = (
    "RussianFreePyramid",
    "RussianCombinedPyramid",
    "RussianDynamicPyramid",
    "RussianClassicPyramid",
)

# method -> (param names, return annotation); copy's return checked per-class
EXPECTED_METHODS = {
    "build_shot_info": (["self", "shot"], ShotInfo),
    "next_shot_constraints": (["self", "shot"], ShotConstraints),
    "initial_shot_constraints": (["self"], ShotConstraints),
    "respot_balls": (["self", "shot"], type(None)),
    "copy": (["self"], None),
}

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(f"{name}: {detail}")


for cls_name in EXPECTED_CLASSES:
    cls = getattr(mod, cls_name, None)
    check(f"{cls_name} exists", cls is not None, "missing")
    if cls is None:
        continue

    check(f"{cls_name} subclasses Ruleset", issubclass(cls, Ruleset))

    for meth_name, (params, ret) in EXPECTED_METHODS.items():
        meth = getattr(cls, meth_name, None)
        check(f"{cls_name}.{meth_name} defined", callable(meth), "missing")
        if meth is None:
            continue

        sig = inspect.signature(meth)
        check(
            f"{cls_name}.{meth_name} signature",
            list(sig.parameters) == params,
            f"got {list(sig.parameters)}, want {params}",
        )

        hints = typing.get_type_hints(meth)
        want_ret = ret if meth_name != "copy" else cls
        check(
            f"{cls_name}.{meth_name} return annotation",
            hints.get("return") is want_ret,
            f"got {hints.get('return')!r}, want {want_ret!r}",
        )

        try:
            meth(None, *(None for _ in params[1:]))
        except NotImplementedError as exc:
            check(f"{cls_name}.{meth_name} raises NotImplementedError", True)
            check(f"{cls_name}.{meth_name} message mentions step", "Step" in str(exc), str(exc))
        except Exception as exc:  # noqa: BLE001
            check(
                f"{cls_name}.{meth_name} raises NotImplementedError",
                False,
                f"raised {type(exc).__name__}: {exc}",
            )

    try:
        cls()
    except NotImplementedError:
        check(f"{cls_name}() surfaces stub via __init__", True)
    except Exception as exc:  # noqa: BLE001
        check(f"{cls_name}() instantiable-or-stub", False, f"{type(exc).__name__}: {exc}")

check("__all__ lists exactly the 4 classes", set(mod.__all__) == set(EXPECTED_CLASSES))

print()
if failures:
    print(f"RESULT: {len(failures)} FAILURE(S)")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("RESULT: ALL CHECKS PASSED")
