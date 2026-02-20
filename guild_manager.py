import argparse
import asyncio
import aiohttp
import configparser
import copy
import logging
import sys
from collections import Counter
from datetime import datetime, UTC
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote


logger = logging.getLogger(Path(__file__).stem)


# https://docs.aiohttp.org/en/stable/client_advanced.html#limiting-connection-pool-size
# default: 100
OPEN_CONNECTIONS_LIMIT = 50
INACTIVE_PLAYER_KILLS = 1000
TOP_STATS_MEMBERS = 10
MEMBER_STATS_LIST = (
    "kills",
    "captured_targets",
    "defended_targets",
    "killed_dolyaks",
)
LOGGING_GW2MISTS_PREFIX = "gw2mists"
LOGGING_GW2_PREFIX = "gw2"


class GW2MISTS_GUILD:
    API_ENDPOINT = "https://api.gw2mists.com"
    API_HEADERS = {
        "referer": "https://gw2mists.com",
        "origin": "https://gw2mists.com",
        "accept": "application/json",
    }

    def __init__(self, guild_name):
        self.guild_name = guild_name
        self._profile = None
        self._unregistered_members = None
        self._team_id = None
        self._wrongteam_members = None
        self._registered_members = None
        self._currentmatch_members = None
        self._members_profiles = None
        self._inactive_members = None
        self._members = None
        self._top_week = None

    async def amember_profile(self, session, *, name):
        url = quote(f"/profile/{name}")
        async with session.get(url) as response:
            profile = await response.json()
            profile["name"] = name
            return profile

    async def amember_profiles(self, names):
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
        async with aiohttp.ClientSession(
            self.API_ENDPOINT,
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=True,
        ) as session:
            tasks = [self.amember_profile(session, name=name) for name in names]
            return await asyncio.gather(*tasks)

    async def aguild_profile(self):
        guild_name_quoted = quote(self.guild_name)
        guild_profile_url = f"{self.API_ENDPOINT}/guilds/{guild_name_quoted}"
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)
        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=True,
        ) as session:
            async with session.get(guild_profile_url) as response:
                return await response.json()

    @property
    def profile(self):
        if self._profile is None:
            self._profile = copy.deepcopy(asyncio.run(self.aguild_profile()))
        return self._profile

    @property
    def unregistered_members(self):
        if self._unregistered_members is None:
            self._unregistered_members = frozenset(
                (
                    x["name"]
                    for x in self.profile["member"]
                    if x["registered"] == 0
                )
            )
        return self._unregistered_members

    @property
    def members(self):
        if self._members is None:
            self._members = frozenset(
                (x["name"] for x in self.profile["member"])
            )
        return self._members

    @property
    def team_id(self):
        if self._team_id is None:
            self._team_id = self.profile["team_id"]
        return self._team_id

    @property
    def wrongteam_members(self):
        if self._wrongteam_members is None:
            self._wrongteam_members = frozenset(
                {
                    x["name"]
                    for x in self.profile["member"]
                    if x["team_id"] != self.team_id
                } - self.unregistered_members
            )
        return self._wrongteam_members

    @property
    def registered_members(self):
        if self._registered_members is None:
            self._registered_members = frozenset(
                (
                    x["name"]
                    for x in self.profile["member"]
                    if x["registered"] == 1
                )
            )
        return self._registered_members

    @property
    def currentmatch_members(self):
        if self._currentmatch_members is None:
            self._currentmatch_members = frozenset(
                self.registered_members - self.wrongteam_members
            )
        return self._currentmatch_members

    @property
    def members_profiles(self):
        if self._members_profiles is None:
            self._members_profiles = {
                x["name"]: x
                for x in asyncio.run(
                    self.amember_profiles(self.registered_members)
                )
            }
        return self._members_profiles

    @property
    def inactive_members(self):
        if self._inactive_members is None:
            self._inactive_members = {
                name: {"kills": kills}
                for name, profile in self.members_profiles.items()
                if (kills:=profile["stats"]["kills"]) < INACTIVE_PLAYER_KILLS
            }
        return self._inactive_members


    def _sorted_members(self, stat, *, reverse):
        return sorted(
            (
                (name, profile["stats"][stat])
                for name, profile in self.members_profiles.items()
            ),
            key=lambda prof: prof[1],
            reverse=reverse,
        )[:TOP_STATS_MEMBERS]

    @property
    def top_week(self):
        if self._top_week is None:
            self._top_week = {}
            for stat in MEMBER_STATS_LIST:
                self._top_week[stat] = self._sorted_members(stat, reverse=True)
        return self._top_week


class GW2_API_KEY:
    API_ENDPOINT = "https://api.guildwars2.com"
    API_HEADERS = {
        "accept": "application/json",
    }

    def __init__(self, api_key):
        self.api_key = api_key
        self.API_HEADERS["authorization"] =  f"Bearer {self.api_key}"
        self._data = None

    async def aapi_key(self):
        api_key_url = f"{self.API_ENDPOINT}/v2/tokeninfo"
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)

        async def status_check(response):
            # override error message
            if response.status == HTTPStatus.BAD_REQUEST:
                response_json = await response.json()
                if error_text := response_json.get("text"):
                    response.reason = f"{response.reason}: {error_text}"
            response.raise_for_status()

        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=status_check,
        ) as session:
            async with session.get(api_key_url) as response:
                return await response.json()

    @property
    def data(self):
        if self._data is None:
            _raw_data = asyncio.run(self.aapi_key())
            self._data = {
                "key": self.api_key,
                "permissions": _raw_data["permissions"],
            }
        return self._data

    @property
    def key(self):
        return self.data["key"]

    @property
    def permissions(self):
        return self.data["permissions"]


class GW2_GUILD:
    API_ENDPOINT = "https://api.guildwars2.com"
    API_HEADERS = {
        "accept": "application/json",
    }

    def __init__(self, name, *, gid, api_key):
        self.name = name
        self.gid = gid
        gw2_api_key = GW2_API_KEY(api_key)
        # guilds - Grants access to guild info under the /v2/guild/:id/ sub-endpoints.
        if not "guilds" in gw2_api_key.permissions:
            raise ValueError(
                f"the api key provided for guild '{self.name}' "
                "doesn't have 'guilds' permission among "
                f"{', '.join(gw2_api_key.permissions)}"
            )
        self.API_HEADERS["authorization"] =  f"Bearer {gw2_api_key.key}"
        self._profile = None
        self._info = None
        self._ranks = None
        self._members = None
        self._wvw_members = None

    async def arequest(self, url):
        connector = aiohttp.TCPConnector(limit=OPEN_CONNECTIONS_LIMIT)

        async def status_check(response):
            # override error message
            if response.status == HTTPStatus.BAD_REQUEST:
                response_json = await response.json()
                if error_text := response_json.get("text"):
                    response.reason = f"{response.reason}: {error_text}"
            response.raise_for_status()

        async with aiohttp.ClientSession(
            connector=connector,
            headers=self.API_HEADERS,
            raise_for_status=status_check,
        ) as session:
            async with session.get(url) as response:
                return await response.json()

    @property
    def profile(self):
        if self._profile is None:
            self._profile = copy.deepcopy(
                asyncio.run(
                    self.arequest(
                        f"{self.API_ENDPOINT}/v2/guild/{self.gid}/members",
                    ),
                )
            )
        return self._profile

    @property
    def info(self):
        if self._info is None:
            self._info = copy.deepcopy(
                asyncio.run(
                    self.arequest(f"{self.API_ENDPOINT}/v2/guild/{self.gid}"),
                )
            )
        return self._info

    @property
    def ranks(self):
        """
        https://wiki.guildwars2.com/wiki/API:2/guild/:id/ranks
        """
        if self._ranks is None:
            self._ranks = copy.deepcopy(
                asyncio.run(
                    self.arequest(
                        f"{self.API_ENDPOINT}/v2/guild/{self.gid}/ranks"
                    ),
                )
            )
        return self._ranks

    @property
    def members(self):
        if self._members is None:
            self._members = frozenset((x["name"] for x in self.profile))
        return self._members

    @property
    def wvw_members(self):
        if self._wvw_members is None:
            self._wvw_members = frozenset(
                (x["name"] for x in self.profile if x["wvw_member"])
            )
        return self._wvw_members


def setup_logging(logfile, *, verbose=False):
    if verbose:
        log_level = logging.DEBUG
        log_format = "%(levelname)-8s : %(name)s : %(message)s"
    else:
        log_level = logging.INFO
        log_format = "%(levelname)-8s : %(message)s"

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(log_level)
    ch.setFormatter(logging.Formatter(log_format))

    handlers = (ch,)
    if logfile:
        fh = logging.FileHandler(logfile, mode="w")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(levelname)-8s : %(message)s"))
        handlers = (*handlers, fh)

    logging.basicConfig(
        handlers=handlers,
        level=logging.DEBUG,
    )


def report_members(
    prefix,
    *,
    message,
    members,
    level=logging.WARNING,
    sort_members=True,
    only_number=False,
):
    fmt = f"{prefix}: {message}: %d"
    if not (len_members := len(members)):
        logging.info(fmt, len_members)
        return
    if only_number:
        logging.log(level, fmt, len_members)
        return
    logger.log(
        level,
        fmt + "\n%s",
        len_members,
        "\n".join(
            (
                f"-> {m}"
                for m in (sorted(members) if sort_members else members)
            )
        ),
    )


def report_members_stats(prefix, *, stats):
    for stat, members in stats.items():
        logging.info(
            "%s (%s):\n%s",
            prefix,
            stat,
            "\n".join((f"-> {m[0]}: {m[1]}" for m in members)),
        )


def report(args, *, logfile):
    logging.info("report time: %s", datetime.now(UTC).isoformat())
    # read guild and alliance settings
    config = configparser.ConfigParser()
    config.read("settings.ini")

    if not args.only_alliance:
        if "guild" not in config:
            raise ValueError(
                "not configured guild in settings.ini "
                "(see settings.ini.in for details)"
            )
        guild_settings = dict(config.items("guild"))

        # alliance is optional in guild report
        if "alliance" not in config:
            alliance_settings = None
        else:
            alliance_settings = dict(config.items("alliance"))
        report_guild(
            guild_settings,
            gw2mists=True,
            gw2=True,
            alliance_settings=alliance_settings,
        )

    if not args.only_guild:
        if "alliance" not in config:
            raise ValueError(
                "not configured alliance in settings.ini "
                "(see settings.ini.in for details)"
            )
        alliance_settings = dict(config.items("alliance"))
        if "api_key" not in alliance_settings:
            raise ValueError(
                "not configured alliance leader api key in settings.ini "
                "(see settings.ini.in for details)"
            )
        report_alliance(alliance_settings)

    logger.info("report to upload: %s", logfile)


def report_guild_gw2mists(
    guild_name,
    *,
    inactive=True,
    stats=True,
    not_registered=True,
    wrong_team=True,
    alliance=False,
):
    gw2mist_guild = GW2MISTS_GUILD(guild_name)
    guild_tag = gw2mist_guild.profile["tag"]
    if not gw2mist_guild.profile["display_roster"]:
        logger.warning(
            "Roster is disabled in guild settings on gw2mists.com "
            f"for '{gw2mist_guild.guild_name}', not able to get members info"
        )
        return

    logging.info(
        f"{LOGGING_GW2MISTS_PREFIX}: %s members number: %d",
        guild_tag,
        gw2mist_guild.profile["member_count"],
    )

    for msg, mbs, only_number  in (
        (
            f"{guild_tag} members on wrong team",
            gw2mist_guild.wrongteam_members,
            not wrong_team,
        ),
        (
            f"{guild_tag} members not registered on gw2mists.com",
            gw2mist_guild.unregistered_members,
            not not_registered,
        ),
        (
            (
                f"registered {guild_tag} members having less than "
                f"{INACTIVE_PLAYER_KILLS} kills during current match"
            ),
            set(
                f"{k} ({v['kills']})"
                for k, v in gw2mist_guild.inactive_members.items()
            ),
            not inactive,
        ),
    ):
        report_members(
            LOGGING_GW2MISTS_PREFIX,
            message=msg,
            members=mbs,
            only_number=only_number,
        )

    if stats:
        report_members_stats(
            f"gw2mists: {guild_tag} top {TOP_STATS_MEMBERS} members",
            stats=gw2mist_guild.top_week,
        )

    if alliance:
        logger.info("reporting guilds in alliance %s", guild_name)
        if not gw2mist_guild.profile["is_alliance"]:
            raise ValueError(f"{guild_name} is not alliance guild")
        for guild in gw2mist_guild.profile["alliance"]["guilds"]:
            report_guild_gw2mists(
                guild["name"],
                inactive=inactive,
                stats=stats,
                not_registered=not_registered,
                wrong_team=wrong_team,
            )


def report_guild_gw2(guild_settings, *, alliance_settings=None):
    # requires guild leader key
    gw2_guild = GW2_GUILD(
        guild_settings["name"],
        gid=guild_settings["gid"],
        api_key=guild_settings["api_key"],
    )
    guild_tag = gw2_guild.info["tag"]
    logging.info(
        f"{LOGGING_GW2_PREFIX}: {guild_tag} members number: %d",
        len(gw2_guild.members),
    )

    # guild is not in any alliance
    if not alliance_settings:
        for msg, mbs in (
            (
                (
                    f"{guild_tag} members that didn't choose [{guild_tag}] as "
                    "wvw guild"
                ),
                gw2_guild.members - gw2_guild.wvw_members,
            ),
        ):
            report_members(
                LOGGING_GW2_PREFIX,
                message=msg,
                members=mbs,
            )
        return

    for msg, mbs in (
        (
            f"{guild_tag} members that chose [{guild_tag}] as wvw guild "
            "instead of alliance",
            gw2_guild.wvw_members,
        ),
    ):
        report_members(
            LOGGING_GW2_PREFIX,
            message=msg,
            members=mbs,
        )

    # don't have alliance leader key
    if "api_key" not in alliance_settings:
        return

    # requires alliance leader key
    gw2_alliance = GW2_GUILD(
        alliance_settings["name"],
        gid=alliance_settings["gid"],
        api_key=alliance_settings["api_key"],
    )

    for msg, mbs in (
        (
            f"{guild_tag} members that didn't join alliance",
            gw2_guild.members-gw2_alliance.members,
        ),
        (
            f"{guild_tag} members that didn't choose alliance as wvw guild",
            gw2_guild.members-(gw2_guild.members&gw2_alliance.wvw_members),
        ),
    ):
        report_members(
            LOGGING_GW2_PREFIX,
            message=msg,
            members=mbs,
        )

    gw2_alliance_rank_names = {r["id"].upper() for r in gw2_alliance.ranks}
    if guild_tag.upper() not in gw2_alliance_rank_names:
        logger.info(
            f"missing guild tag ({guild_tag.upper()}) in alliance ranks: "
            f"{gw2_alliance_rank_names}"
        )
    else:
        for msg, mbs in (
            (
                (
                    f"{guild_tag} members that don't have '{guild_tag}' or "
                    "special alliance rank"
                ),
                [
                    f"{p['name']}: {p['rank']}"
                    for m in gw2_guild.members & gw2_alliance.members
                    for p in gw2_alliance.profile
                    if (
                        m == p["name"]
                        and p["rank"].upper() not in (
                            guild_tag.upper(),
                            "OFFICER",
                            "LEADER",
                        )
                    )
                ],
            ),
            (
                (
                    f"NOT {guild_tag} members that have '{guild_tag}' alliance "
                    "rank"
                ),
                [
                    f"{p['name']}: {p['rank']}"
                    for p in gw2_alliance.profile
                    if (
                        p["rank"].upper() == guild_tag.upper()
                        and p["name"] not in (
                            gw2_guild.members & gw2_alliance.members
                        )
                    )
                ],
            ),
        ):
            report_members(
                LOGGING_GW2_PREFIX,
                message=msg,
                members=mbs,
            )


def report_guild(
    guild_settings,
    *,
    alliance_settings=None,
    gw2mists=True,
    gw2=True,
):
    logging.info("guild name: %s", guild_settings["name"])
    if gw2mists:
        report_guild_gw2mists(guild_settings["name"])

    if gw2:
        report_guild_gw2(guild_settings, alliance_settings=alliance_settings)


def report_alliance(alliance_settings):
    logging.info("alliance guild name: %s", alliance_settings["name"])

    report_guild_gw2mists(
        alliance_settings["name"],
        inactive=False,
        stats=True,
        not_registered=False,
        alliance=True,
    )

    gw2_alliance = GW2_GUILD(
        alliance_settings["name"],
        gid=alliance_settings["gid"],
        api_key=alliance_settings["api_key"],
    )
    logging.info(
        f"{LOGGING_GW2_PREFIX}: alliance members number: %d",
        len(gw2_alliance.members),
    )

    report_members(
        LOGGING_GW2_PREFIX,
        message="alliance ranks",
        members=[
            f"{g}: {n}"
            for g, n in Counter(
                p["rank"] for p in gw2_alliance.profile
            ).most_common()
        ],
        level=logging.INFO,
        sort_members=False,
    )


def main_parser():
    parser = argparse.ArgumentParser(description="report guild stats")

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    parser.add_argument(
        "--logfile",
        help="Logfile path",
    )

    guild_group = parser.add_mutually_exclusive_group(required=True)
    guild_group.add_argument(
        "--only-alliance",
        action="store_true",
        help="Only alliance report",
    )

    guild_group.add_argument(
        "--only-guild",
        action="store_true",
        help="Only guild report",
    )

    parser.set_defaults(main=report)
    return parser


def main(cli_args):
    parser = main_parser()
    args = parser.parse_args(cli_args)
    if not (logfile := args.logfile):
        default=f"report_{datetime.now(UTC).isoformat()}.log"
        logfile = f"{'guild' if args.only_guild else 'alliance'}_{default}"
    setup_logging(logfile, verbose=args.verbose)
    args.main(args, logfile=logfile)


if __name__ == "__main__":
    main(sys.argv[1:])
