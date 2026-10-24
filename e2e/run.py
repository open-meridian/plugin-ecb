"""`make e2e`: the plugin on the plugin harness of the runtime it pins
(contract v27), beside `reader`, a reporting plugin (e2e/reader.py) entitled
to its dataset, and the harness's admin. Run from the repository's root by
the Makefile, which builds the image and writes the harness's plugins first;
standard library only.

1. The portal unreachable: the plugin's hosts file sends the ECB's portal
   nowhere, so its first check fails, and Connection says so -- "Not
   answering", the data role's word -- and records nothing.
2. Sample data on (a developer's setting, accepted on the harness): the
   plugin reads the committed answer's last ten days, 9 to 19 October 2026,
   resolves the euro and the 29 currencies to cash instruments, and records
   203 rates; Datasets lists each currency with its instrument.
3. Parity: through the deployment's MCP, `read_connection` and
   `read_datasets` answer what the pages show, under the data role's names
   -- the days read, the portal's Last-Modified, every currency's
   instrument -- and core's `dashboard__list_datasets` lists `ecb:ecb_fx`
   as the catalogue declares it: push and pull, daily, Frankfurt's day
   ending at midnight, TARGET's calendar.
4. Licensed and entitled at the Data sources page: the reader is entitled.
5. Read back: the euro's cash instrument on 19 October 2026 is priced in 29
   currencies, dollars at 1.1225 in the dollar's instrument; each a close,
   version 1, the published time the portal's Last-Modified.
6. Wanted: a day not recorded, 25 September, is asked of the plugin, which
   reads it from the portal and records it against the want; the reader
   then reads it. A day the portal states nothing for, Friday 31 July,
   is declined `source_silent`; the dollar's own instrument, which the ECB
   never prices (it quotes dollars per euro, and nothing inverts it),
   `not_covered`.
7. `store lake` is e2e/expected.lake, each subject named by its ISO code.
8. A new container: it reads the rates again and records nothing twice;
   the lake is unchanged.

€STR (`ecb_estr`, 0.2.0), beside them: sample data's €STR read to 22
October 2026; each of its seven records resolved by its symbol at the ECB to
the platform's seeded `INS-` record, never minted (core's harness from
a5da59a holds them); the current range recorded, then the history before it
backfilled once; core listing `ecb:ecb_estr` as declared; licensed and entitled; and read back by the reader: €STR of 22
October a fixing of 2.442 per cent, act/360 simple, with its volume, count,
percentiles and published time, the index an index level based 1 October
2019 = 100, and a backfilled day with no published time. In the lake each
€STR subject is named by its seed's code.
"""

import json
import os
import subprocess
import sys
import time

PROJECT = "ecb-e2e"
LOG = ".e2e/runner.log"
COMPONENTS = ".e2e/components.log"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", ".e2e/harness/compose.yaml",
           "-f", ".e2e/harness/plugins.yaml", "-f", "e2e/plugin.yaml"]
DATASET = "ecb:ecb_fx"
#: Seconds after the deployment starts by which its conductor has read the
#: platform's licence list: core's FIRST_AGAIN_AFTER (60 s) and a margin.
LICENCE_LIST_READ = 80
ESTR = "ecb:ecb_estr"


class Failed(Exception):
    pass


def log(text):
    with open(LOG, "a", encoding="utf-8") as kept:
        kept.write(text + "\n")


def compose(*args, check=True, timeout=600):
    done = subprocess.run(COMPOSE + list(args), capture_output=True, text=True,
                          timeout=timeout)
    log(f"$ compose {' '.join(args)[:300]}\n{done.stdout[-4000:]}{done.stderr[-2000:]}")
    if check and done.returncode != 0:
        raise Failed(f"compose {' '.join(args)[:200]}: {(done.stdout + done.stderr).strip()[-600:]}")
    return done


def runner(*args, check=True):
    done = compose("run", "--rm", "-T", "runner", *args, check=check)
    return done.stdout if check else done


def must(condition, why):
    if not condition:
        raise Failed(why)


def until(seconds, attempt, what):
    deadline = time.monotonic() + seconds
    last = None
    while True:
        try:
            answer = attempt()
        except Failed as failed:
            answer, last = None, failed
        if answer:
            return answer
        if time.monotonic() > deadline:
            raise Failed(f"{what}, in {seconds} seconds" + (f": {last}" if last else ""))
        time.sleep(2)


def page(instance, level, path):
    said = runner("page", "--instance", instance, "--level", level, path)
    status, _, body = said.partition("\n")
    must(status.strip() == "200", f"{instance} {path} answered {said[-600:]}")
    return body


def prices(subject, day):
    """The reader's read of the plugin's dataset, by business date."""
    body = page("reader", "read", f"/prices?subject={subject}&date={day}&dataset={DATASET}&kind=close")
    return json.loads(body)


def call(tool, arguments=None):
    done = runner("mcp", "call", tool, json.dumps(arguments or {}), check=False)
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        raise Failed(f"{tool}: no answer: {(done.stdout + done.stderr)[-400:]}")
    must(answer.get("outcome") in ("read", "unchanged"), f"{tool} answered {done.stdout[-700:]}")
    return answer["data"]


def store_lake():
    return compose("run", "--rm", "-T", "store", "lake").stdout


def named(lines, codes):
    """`store lake` with each subject's ID, drawn per run, as its ISO code."""
    out = []
    for line in lines.strip().splitlines():
        parts = line.split("|")
        if parts[0] == "row":
            parts[6] = codes.get(parts[6], parts[6])
        elif parts[0] == "want":
            parts[3] = ",".join(codes.get(s, s) for s in parts[3].split(","))
        out.append("|".join(parts))
    return "\n".join(sorted(out)) + "\n"


def run():
    started = time.time()
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    compose("up", "-d")
    up_at = time.monotonic()
    runner("ready")
    runner("ready", "--instance", "reader")

    # 1. The portal unreachable.
    page_said = runner("page", "--level", "admin", "/", "--until", "Not answering",
                       "--seconds", "90")
    must("ConnectionRefusedError" in page_said or "URLError" in page_said or "Error" in page_said,
         f"step 1, Connection names why the portal was not reached: {page_said[-500:]}")
    lake = store_lake()
    must("row|" not in lake, f"step 1, nothing recorded with the portal unreachable: {lake}")

    # 2. Sample data: the last ten days of the committed answer recorded.
    # €STR's records are asked of the platform by the ECB's own code, which
    # the deployment sends only once it has read the platform's licence list
    # naming the ECB (ruling 545): the conductor reads it on start, and a
    # minute later where the stand-in platform was not up yet. Sample data
    # waits for that, so the first read resolves the seven records; the
    # plugin would otherwise find them at its next hourly check.
    time.sleep(max(0.0, LICENCE_LIST_READ - (time.monotonic() - up_at)))
    runner("settings", "sample_data=true")
    runner("page", "--level", "admin", "/datasets", "--until", 'data-code="ZAR"', "--seconds", "120")
    runner("page", "--level", "admin", "/", "--until", "Mon 19 Oct", "--seconds", "60")
    until(60, lambda: store_lake().count("row|ecb:ecb_fx|price|") >= 203,
          "step 2, the 203 current rates were not recorded")

    # 3. Parity through the deployment's MCP, and core's view of the catalogue.
    runner("grant", "--level", "admin")
    runner("mcp", "connect", "--covers", "deployment_admin", "--covers", "ecb:admin")
    tools = runner("mcp", "list").split()
    read_connection = next((t for t in tools if t.endswith("read_connection")), "")
    read_datasets = next((t for t in tools if t.endswith("read_datasets")), "")
    must(read_connection and read_datasets, f"step 3, the plugin's two tools are listed: {tools}")
    connection = call(read_connection)
    must(connection["latest_day"] == "2026-10-19" and connection["first_day"] == "2026-10-09"
         and connection["mode"] == "Sample data" and connection["credentials"] == []
         and connection["sessions"] is None
         and connection["published_at"] == "2026-10-19T13:56:57+00:00"
         and connection["sources"][0]["dataset"] == DATASET,
         f"step 3, read_connection: {connection}")
    datasets = call(read_datasets)
    codes = {r["instrument_id"]: r["code"] for r in datasets["records"] if r["instrument_id"]}
    ids = {code: instrument for instrument, code in codes.items()}
    must(len(ids) == 30 and datasets["served"][0]["dataset"] == DATASET,
         f"step 3, read_datasets names 30 instruments: {datasets}")
    shown = page("ecb", "admin", "/datasets")
    must(all(instrument in shown for instrument in codes), "step 3, Datasets shows what read_datasets answers")
    listed = {d["dataset"]: d for d in call("dashboard__list_datasets")["datasets"]}
    entry = listed.get(DATASET, {}).get("catalogue_entry", {})
    must(entry.get("modes") == ["push", "pull"] and entry.get("day_time_zone") == "Europe/Berlin"
         and not entry.get("day_end_minute") and entry.get("cadence") == 86400
         and entry.get("calendar_id") == "CAL-01M4VF0F5ZRTY7AZ3B36ZVWN11",
         f"step 3, core lists the catalogue as declared: {listed.get(DATASET)}")
    # €STR: read, its seven records resolved, the history backfilled once.
    estr_entry = listed.get(ESTR, {}).get("catalogue_entry", {})
    must(estr_entry.get("modes") == ["push", "pull"] and estr_entry.get("history") == 2600
         and "meridian.v1.Rate" in estr_entry.get("data_types", [])
         and estr_entry.get("calendar_id") == "CAL-01M4VF0F5ZRTY7AZ3B36ZVWN11",
         f"step 3, core lists ecb_estr as declared: {listed.get(ESTR)}")
    estr_read = until(120, lambda: (lambda s: s if s.get("last_release") == "2026-10-22"
                                    and s.get("history") == "Done through 2026-10-11" else None)(
        next((s for s in call(read_connection)["sources"] if s["dataset"] == ESTR), {})),
        "step 3, €STR read to 22 October and its history backfilled")
    rates = call(read_datasets)["rates"]
    must(len(rates) == 7 and all(r["instrument_id"].startswith("INS-") and not r["miss"] for r in rates)
         and rates[0]["code"] == "ESTR" and rates[0]["series"] == "EST.B.EU000A2X2A25.WT",
         f"step 3, the seven €STR records resolved: {rates}")
    for r in rates:
        codes[r["instrument_id"]] = r["code"]
    estr_ids = {r["code"]: r["instrument_id"] for r in rates}
    until(60, lambda: store_lake().count(f"row|{ESTR}|rate|") >= 413,
          f"step 3, €STR's current range and history recorded: {estr_read}")

    # 4. Licensed and entitled.
    runner("licence", DATASET, "kept=true", "retention_days=0", "derived_use=true", "display=true",
           "personal_use=false", "note=The ECB's reference rates: free use, citing the ECB.")
    runner("entitle", "--instance", "reader", DATASET, "note=The e2e's reader reads the rates.")
    runner("licence", ESTR, "kept=true", "retention_days=0", "derived_use=true", "display=true",
           "personal_use=false", "note=€STR: free use, citing the ECB.")
    runner("entitle", "--instance", "reader", ESTR, "note=The e2e's reader reads €STR.")
    runner("grant", "--instance", "reader", "--level", "read")

    # 5. Read back, in the right instruments.
    read = until(60, lambda: (lambda r: r if len(r["prices"]) == 29 else None)(prices(ids["EUR"], "2026-10-19")),
                 "step 5, the euro's 29 prices on 19 October were not read")
    dollar = [p for p in read["prices"] if p["row_key"] == "USD:2026-10-19"]
    must(dollar and dollar[0]["amount"] == "1.1225" and dollar[0]["instrument_id"] == ids["USD"]
         and dollar[0]["kind"] == "PRICE_KIND_CLOSE" and dollar[0]["version"] == 1
         and dollar[0]["business_date"] == "2026-10-19"
         and dollar[0]["published"] == [1792418217 * 10**9],
         f"step 5, the euro priced in dollars as the ECB quotes it: {dollar}")
    earlier = prices(ids["EUR"], "2026-10-16")["prices"]
    must(len(earlier) == 29 and not any(p["published"] for p in earlier),
         f"step 5, a rate read after its day states no published time: {earlier[:2]}")

    # €STR read back: the fixing with its volume, count, percentiles and
    # published time; the index; a backfilled day stating no published time.
    def rates_of(code, day):
        body = page("reader", "read", f"/rates?subject={estr_ids[code]}&date={day}&dataset={ESTR}")
        return json.loads(body)["rates"]
    fixing = until(60, lambda: rates_of("ESTR", "2026-10-22"), "step 5, €STR of 22 October not read")
    must(len(fixing) == 1 and fixing[0]["kind"] == "RATE_KIND_FIXING" and fixing[0]["value"] == "2.442"
         and fixing[0]["unit"] == "VALUE_UNIT_PERCENT" and fixing[0]["day_count"] == "DAY_COUNT_ACT_360"
         and fixing[0]["compounding"] == "COMPOUNDING_SIMPLE" and fixing[0]["volume"] == "61438000000"
         and fixing[0]["transaction_count"] == 847 and fixing[0]["percentiles"] == {"25": "2.41", "75": "2.45"}
         and fixing[0]["published"] == [1792740016 * 10**9] and fixing[0]["version"] == 1,
         f"step 5, €STR of 22 October as the ECB published it: {fixing}")
    index = rates_of("ESTR compounded index", "2026-10-22")
    must(len(index) == 1 and index[0]["kind"] == "RATE_KIND_INDEX_LEVEL" and index[0]["value"] == "110.05474139"
         and index[0]["unit"] == "VALUE_UNIT_INDEX" and index[0]["index_base"] == "2019-10-01=100",
         f"step 5, the compounded index of 22 October: {index}")
    month = rates_of("ESTR 1-month compounded average", "2026-09-25")
    must(len(month) == 1 and month[0]["kind"] == "RATE_KIND_AVERAGE" and not month[0]["published"],
         f"step 5, a backfilled average states no published time: {month}")

    # 6. Wants: a past day recorded against one; a day the portal states
    # nothing for and a subject not covered declined.
    asked = prices(ids["EUR"], "2026-09-25")
    must(asked["prices"] or any(u["reason"] == "UNANSWERED_REASON_ASKED_SOURCE" for u in asked["unanswered"]),
         f"step 6, 25 September is asked of the plugin: {asked}")
    past = until(90, lambda: (lambda r: r if len(r["prices"]) == 29 else None)(prices(ids["EUR"], "2026-09-25")),
                 "step 6, 25 September was not recorded against the want")
    yen = [p for p in past["prices"] if p["row_key"] == "JPY:2026-09-25"]
    must(yen and yen[0]["instrument_id"] == ids["JPY"], f"step 6, 25 September's yen: {yen}")
    prices(ids["EUR"], "2026-07-31")
    prices(ids["USD"], "2026-10-19")
    until(90, lambda: "|declined|" in store_lake() and store_lake().count("|declined|") >= 2,
          "step 6, the day stated nothing for and the dollar's instrument were not declined")

    # 7. The lake.
    lines = store_lake()
    got = named(lines, codes)
    with open(".e2e/lake", "w", encoding="utf-8") as kept:
        kept.write(got)
    with open("e2e/expected.lake", encoding="utf-8") as held:
        expected = held.read()
    if got != expected:
        diff = subprocess.run(["diff", "-u", "e2e/expected.lake", ".e2e/lake"], capture_output=True, text=True)
        raise Failed(f"step 7, the lake is not e2e/expected.lake:\n{diff.stdout[-3000:]}")

    # 8. A new container records nothing twice.
    compose("up", "-d", "--no-deps", "--force-recreate", "ecb")
    runner("ready")
    until(120, lambda: "Mon 19 Oct" in page("ecb", "admin", "/"),
          "step 8, the new container did not read the rates again")
    time.sleep(5)
    again = named(store_lake(), codes)
    must(again == got, "step 8, the new container recorded something twice:\n"
         + subprocess.run(["diff", "-u", "-", ".e2e/lake"], input=again, capture_output=True, text=True).stdout[-2000:])
    logs = compose("logs", "--no-color", "ecb").stdout
    must("0 recorded, 0 restated, 203 unchanged" in logs,
         "step 8, the new container's check was answered unchanged: " + logs[-800:])
    until(90, lambda: all(s["licensed"] for s in call(read_datasets)["served"]),
          "step 8, the new container never read its dataset's licence")

    rows = got.count("row|")
    print(f"e2e OK in {int(time.time() - started)}s on the plugin harness: the ECB's portal unreachable "
          f"said on Connection, nothing recorded; sample data's 9 to 19 October 2026 recorded, 30 "
          f"currencies resolved; read_connection and read_datasets answering what the pages show, and "
          f"core listing {DATASET} as declared; licensed and entitled; the euro priced in 29 currencies "
          f"(dollars 1.1225), each a close on its business date, the portal's published time on the day "
          f"read on its day; 25 September wanted and recorded, 31 July declined source silent and the "
          f"dollar's own instrument not covered; €STR's seven records resolved to the platform's "
          f"seeded records, its current range and history recorded once, and read back (2.442 "
          f"per cent, act/360, with volume, count, percentiles and published time; the index "
          f"based 2019-10-01=100); `store lake` as e2e/expected.lake ({rows} rows); and a new container recording nothing twice, "
          f"its licence read on start")


def main():
    os.makedirs(".e2e", exist_ok=True)
    open(LOG, "w").close()
    try:
        run()
    except (Failed, subprocess.TimeoutExpired, KeyError, ValueError, IndexError, TypeError) as failed:
        with open(COMPONENTS, "a", encoding="utf-8") as kept:
            kept.write(compose("logs", "--no-color", check=False).stdout)
        compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
        print(f"e2e FAILED: {failed}; the runner's log is in {LOG}, the components' in {COMPONENTS}",
              file=sys.stderr)
        return 1
    compose("--profile", "runner", "down", "-v", "--remove-orphans", check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
