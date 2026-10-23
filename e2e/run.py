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

€STR (`ecb_estr`, 0.2.0) is proven up to recording: core's harness at
c786b9a does not hold the platform's seeded `ecb:` referential records yet,
so sample data's €STR is read (its latest day 22 October 2026), each of its
seven records asked of the deployment and reported missing -- `miss|ecb|7`
in the lake, never minted -- and no row recorded; core lists `ecb:ecb_estr`
as declared, and `read_datasets` names the seven not held. Recording them
is proven by the unit tests and the data suite until the harness seeds them.
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
    # €STR, up to recording: read, its seven records asked and not held.
    estr_entry = listed.get(ESTR, {}).get("catalogue_entry", {})
    must(estr_entry.get("modes") == ["push", "pull"] and estr_entry.get("history") == 2600
         and "meridian.v1.Rate" in estr_entry.get("data_types", [])
         and estr_entry.get("calendar_id") == "CAL-01M4VF0F5ZRTY7AZ3B36ZVWN11",
         f"step 3, core lists ecb_estr as declared: {listed.get(ESTR)}")
    estr_source = next((s for s in connection["sources"] if s["dataset"] == ESTR), {})
    estr_read = until(60, lambda: (lambda s: s if s.get("last_release") == "2026-10-22" else None)(
        next((s for s in call(read_connection)["sources"] if s["dataset"] == ESTR), {})),
        f"step 3, €STR's sample read to 22 October: {estr_source}")
    rates = call(read_datasets)["rates"]
    must(len(rates) == 7 and all(not r["instrument_id"] and r["miss"] for r in rates)
         and rates[0]["code"] == "ESTR" and rates[0]["series"] == "EST.B.EU000A2X2A25.WT",
         f"step 3, the seven €STR records asked and not held: {rates}")
    must("Waiting: 7 of 7 records not held" in estr_read["history"],
         f"step 3, the history waits for the records: {estr_read}")
    must(f"row|{ESTR}|" not in store_lake() and "miss|ecb|7" in store_lake(),
         "step 3, no €STR row recorded, its seven records reported missing")

    # 4. Licensed and entitled.
    runner("licence", DATASET, "kept=true", "retention_days=0", "derived_use=true", "display=true",
           "personal_use=false", "note=The ECB's reference rates: free use, citing the ECB.")
    runner("entitle", "--instance", "reader", DATASET, "note=The e2e's reader reads the rates.")
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
    # The new container asks for €STR's records again, and counts its misses
    # again: compared without them.
    def rows_only(lines):
        return "".join(line + "\n" for line in lines.splitlines() if not line.startswith("miss|"))
    again = named(store_lake(), codes)
    must(rows_only(again) == rows_only(got), "step 8, the new container recorded something twice:\n"
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
          f"dollar's own instrument not covered; €STR read to 22 October, its seven records asked "
          f"and reported missing (the harness holds no ecb: record yet), none recorded; `store "
          f"lake` as e2e/expected.lake ({rows} rows); and a new container recording nothing twice, "
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
