"""Write flash.par from flash.toml files in the Flash-X tomlfile format.

Mirrors bin/createParfile.py in Flash-X, which only runs at setup. Setup
checks the base parameters against setup_params, so this script trusts them.

jobrunner writes job.input only during setup, not submit, so a case built
from the base executable has none. The base flash.toml and the case's
flash.toml are merged here the way jobrunner's CreateInputFile does: each
top-level table of a later file updates the same table of an earlier one.
A case sets its values in [Override.<Unit>] tables, which are applied to the
base and checked against it. [Physical] holds re-dimensionalization data for
analysis and is not passed to Flash-X. Heater site tables (e.g.
[Heater.0001]) are skipped; the heater file comes from setup.
"""

import argparse
import toml

# Tables in the inputs that are not Flash-X units
CASE_TABLES = ["Override", "Physical"]


def mergeInputs(filenames):
    """
    Merge toml files, later files updating top-level tables of earlier ones
    """
    inputDict = {}
    for filename in filenames:
        for group, params in toml.load(filename).items():
            if group in inputDict:
                inputDict[group].update(params)
            else:
                inputDict[group] = params

    return inputDict


def applyOverrides(inputDict):
    """
    Apply [Override.<Unit>] values to the base unit tables
    """
    for group, params in inputDict.get("Override", {}).items():
        if group not in inputDict:
            raise SystemExit(f'[Override.{group}] has no matching [{group}] table in the base flash.toml')

        for key, value in params.items():
            if key not in inputDict[group]:
                raise SystemExit(f'Override "{group}.{key}" is not set in the base flash.toml; '
                                 + "add it there so setup checks it")
            inputDict[group][key] = value

    return inputDict


def createParfile(inputDict):
    """
    Create flash.par
    """
    with open("flash.par", "w") as parfile:

        parfile.write("# Programmatically generated parfile for flashx\n")

        for group, params in inputDict.items():
            if group in CASE_TABLES:
                continue

            parfile.write(f"\n# Runtime parameters for {group}\n")

            for key, value in params.items():
                if isinstance(value, dict):
                    continue

                if isinstance(value, bool):
                    parfile.write(f"{key} = .{str(value).upper()}.\n")
                elif isinstance(value, str):
                    parfile.write(f'{key} = "{value}"\n')
                else:
                    parfile.write(f"{key} = {value}\n")

    print(f"Wrote parameter information to file flash.par")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create flash.par from flash.toml files")
    parser.add_argument("--input", nargs="+", required=True,
                        help="tomlfiles to merge, base first")
    args = parser.parse_args()

    createParfile(applyOverrides(mergeInputs(args.input)))
