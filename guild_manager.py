import asyncio
import aiohttp
import configparser
import copy
import logging
import sys
from datetime import datetime, UTC
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote


logger = logging.getLogger(Path(__file__).stem)


# https://docs.aiohttp.org/en/stable/client_advanced.html#limiting-connection-pool-size
# default: 100
OPEN_CONNECTIONS_LIMIT = 50
GUILD_NAME = "Dodge Right I Mean"
ALLIANCE_GUILD_NAME = "Glub Glub Glub Glub Glub"
INACTIVE_PLAYER_KILLS = 1000
TOP_STATS_MEMBERS = 10
MEMBER_STATS_LIST = (
    "kills",
    "captured_targets",
    "defended_targets",
    "killed_dolyaks",
)


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


class GW2_GUILD:
    API_ENDPOINT = "https://api.guildwars2.com"
    API_HEADERS = {
        "accept": "application/json",
    }

    def __init__(self, guild_name):
        self.guild_name = guild_name

        config = configparser.ConfigParser()
        config.read("settings.ini")
        if self.guild_name not in config:
            raise ValueError(
                f"not configured guild: {self.guild_name}, "
                "see settings.ini.in for details"
            )
        self.gid = config[self.guild_name]["gid"]
        self.api_key = config[self.guild_name]["api_key"]
        self.API_HEADERS["authorization"] =  f"Bearer {self.api_key}"
        self._profile = None
        self._members = None
        self._wvw_members = None

    async def aguild_profile(self):
        guild_profile_url = f"{self.API_ENDPOINT}/v2/guild/{self.gid}/members"
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
            async with session.get(guild_profile_url) as response:
                return await response.json()

    @property
    def profile(self):
        if self._profile is None:
            self._profile = copy.deepcopy(asyncio.run(self.aguild_profile()))
        return self._profile

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


def report_members(prefix, *, message, members):
    fmt = f"{prefix}: {message}: %d"
    if (len_members := len(members)):
        logging.warning(
            fmt + "\n%s",
            len_members,
            "\n".join((f"-> {m}" for m in sorted(members))),
        )
    else:
        logging.info(fmt, len_members)


def report_members_stats(prefix, *, stats):
    for stat, members in stats.items():
        logging.info(
            "%s (%s):\n%s",
            prefix,
            stat,
            "\n".join((f"-> {m[0]}: {m[1]}" for m in members)),
        )


def main():
    now = datetime.now(UTC).isoformat()
    logfile = f"report_{now}.log"
    setup_logging(logfile)
    logging.info("report time: %s", now)
    logging.info("guild name: %s", GUILD_NAME)
    logging.info("alliance guild name: %s", ALLIANCE_GUILD_NAME)

    gw2mist_guild = GW2MISTS_GUILD(GUILD_NAME)
    if not gw2mist_guild.profile["display_roster"]:
        raise ValueError(
            "Roster is disabled in guild settings on gw2mists.com "
            f"for '{gw2mist_guild.guild_name}', not able to get members info"
        )
    gw2mist_alliance = GW2MISTS_GUILD(ALLIANCE_GUILD_NAME)
    if not gw2mist_alliance.profile["display_roster"]:
        raise ValueError(
            "Roster is disabled in guild settings on gw2mists.com "
            f"for '{gw2mist_alliance.guild_name}', not able to get members info"
        )

    logging_gw2mists_prefix = "gw2mists"
    logging.info(
        f"{logging_gw2mists_prefix}: total guild member number: %d",
        gw2mist_guild.profile["member_count"],
    )

    for msg, mbs in (
        (
            "guild members not registered on gw2mists.com",
            gw2mist_guild.unregistered_members,
        ),
        ("guild members on wrong team", gw2mist_guild.wrongteam_members),
        (
            f"guild members having less than {INACTIVE_PLAYER_KILLS} kills "
            "during current match",
            set(f"{k} ({v['kills']})" for k, v in gw2mist_guild.inactive_members.items()),
        ),
        (
            f"alliance members having less than {INACTIVE_PLAYER_KILLS} kills "
            "during current match",
            set(f"{k} ({v['kills']})" for k, v in gw2mist_alliance.inactive_members.items()),
        ),
    ):
        report_members(
            logging_gw2mists_prefix,
            message=msg,
            members=mbs,
        )

    logging_gw2_prefix = "gw2"
    gw2_guild = GW2_GUILD(GUILD_NAME)
    logging.info(
        f"{logging_gw2_prefix}: total guild member number: %d",
        len(gw2_guild.members),
    )

    gw2_alliance = GW2_GUILD(ALLIANCE_GUILD_NAME)
    logging.info(
        f"{logging_gw2_prefix}: total alliance member number: %d",
        len(gw2_alliance.members),
    )


    for msg, mbs in (
        (
            "not registered guild members that didn't join alliance",
            gw2mist_guild.unregistered_members-gw2_alliance.members,
        ),
        (
            "guild members that didn't join alliance",
            gw2_not_alliance_members:=gw2_guild.members-gw2_alliance.members,
        ),
        (
            "inactive guild members that didn't join alliance",
            set(gw2mist_guild.inactive_members)&gw2_not_alliance_members,
        ),
        (
            f"guild members that chose [{GUILD_NAME}] as wvw guild "
            "instead of alliance",
            gw2_guild.wvw_members,
        ),
        (
            "guild members that didn't choose alliance as wvw guild",
            gw2_guild.members-(gw2_guild.members&gw2_alliance.wvw_members),
        ),
    ):
        report_members(
            logging_gw2_prefix,
            message=msg,
            members=mbs,
        )

    for msg, stats in (
        (f"gw2mists: guild top {TOP_STATS_MEMBERS} members", gw2mist_guild.top_week),
        (f"gw2mists: alliance top {TOP_STATS_MEMBERS} members", gw2mist_alliance.top_week),
    ):
        report_members_stats(msg, stats=stats)

    logger.info("logfile to upload: %s", logfile)


if __name__ == "__main__":
    main()
