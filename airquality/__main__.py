"""One entry point for every step of the project: ``python -m airquality <command>``.

Research pipeline (reads the locked data snapshot, writes to ``reports/``)::

    python -m airquality pipeline      # train + intervals + decisions + explain
    python -m airquality train         # compare, select and test the model
    python -m airquality intervals     # calibrate the 90% forecast ranges
    python -m airquality decisions     # exceedance probabilities and alert scores
    python -m airquality explain       # what drives each horizon's forecast

Data (needs network access to the public sources)::

    python -m airquality data          # download and rebuild the dataset
    python -m airquality lock          # freeze the rebuilt dataset for modelling

Operations::

    python -m airquality refresh       # the scheduled job: issue and score forecasts
    python -m airquality notebook      # re-run AirQuality.ipynb in place
"""

import argparse
import json


def data(args):
    from airquality import forecast_inputs
    from airquality.extend import extend

    daily, manifest = extend(args.end_date, refresh=True)
    forecast_inputs.update(daily.index[-1])
    print(f"Dataset rebuilt through {manifest['end']}. Review it, then run: lock")


def lock(args):
    from airquality.contract import DEFAULT_INPUT, validate

    _, record = validate(DEFAULT_INPUT, require_lock=False)
    DEFAULT_INPUT.with_suffix(".lock.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(json.dumps(record, indent=2))


def train(args):
    from airquality import training

    validation, _, test = training.run()
    print(validation.groupby("model").MAE.mean().sort_values().round(2).to_string())
    print(test.groupby("model").MAE.mean().sort_values().round(2).to_string())


def intervals(args):
    from airquality import uncertainty

    print(uncertainty.calibrate().round(3).to_string(index=False))


def decide(args):
    from airquality import decisions

    _, summary = decisions.run()
    print(json.dumps(summary, indent=2))


def explain(args):
    from airquality import explain as module

    table = module.run()
    print(
        table.pivot(index="label", columns="horizon", values="MAE_increase")
        .round(2)
        .to_string()
    )


def pipeline(args):
    for step in (train, intervals, decide, explain):
        print(f"\n== {step.__name__} ==")
        step(args)


def refresh(args):
    from airquality import operations

    try:
        print(json.dumps(operations.run(refresh=not args.snapshot), indent=2))
    except operations.PublicationBlocked as blocked:
        # Shown as a notice in the GitHub Actions run summary; the job stays green.
        print(f"::notice title=No forecast issued::{blocked}")


def notebook(args):
    from scripts.execute_notebook import execute

    execute("AirQuality.ipynb")


COMMANDS = {
    "pipeline": (pipeline, "train, intervals, decisions and explain, in order"),
    "train": (train, "compare, select and test the forecasting model"),
    "intervals": (intervals, "calibrate the 90% forecast ranges"),
    "decisions": (decide, "exceedance probabilities and alert scores"),
    "explain": (explain, "what drives each horizon's forecast"),
    "data": (data, "download the sources and rebuild the dataset"),
    "lock": (lock, "freeze the rebuilt dataset for modelling"),
    "refresh": (refresh, "issue today's forecast and score earlier ones"),
    "notebook": (notebook, "re-run AirQuality.ipynb in place"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m airquality", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (function, summary) in COMMANDS.items():
        sub = commands.add_parser(name, help=summary)
        sub.set_defaults(function=function)
        if name == "data":
            sub.add_argument("--end-date", help="last day to include (default: today)")
        if name == "refresh":
            sub.add_argument(
                "--snapshot",
                action="store_true",
                help="use the locked dataset instead of downloading fresh data",
            )
    args = parser.parse_args(argv)
    args.function(args)


if __name__ == "__main__":
    main()
