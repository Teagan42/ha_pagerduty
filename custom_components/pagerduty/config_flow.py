"""Config flow for PagerDuty integration."""
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.selector import (
    TemplateSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from pagerduty import RestApiV2Client, Error

from .const import DOMAIN, REQUIRED_ROLES

_LOGGER = logging.getLogger(__name__)


class PagerDutyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PagerDuty integration."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return PagerDutyOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            api_base_url = self._get_api_url(
                user_input.get("api_server", "US")
            )

            valid, user_data = await self.hass.async_add_executor_job(
                self._test_api_key_and_fetch_user_data,
                user_input[CONF_API_KEY],
                api_base_url,
            )
            if valid:
                user_input.update(user_data)
            else:
                errors["base"] = "invalid_api_key_or_roles"

            if not errors:
                user_input["api_base_url"] = api_base_url
                return self.async_create_entry(
                    title="PagerDuty", data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                    vol.Optional("ignored_team_ids", default=""): str,
                    vol.Optional("api_server", default="US"): vol.In(
                        ["US", "EU"]
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def _get_api_url(api_server):
        """Return the API base URL based on the server choice."""
        return (
            "https://api.pagerduty.com"
            if api_server == "US"
            else "https://api.eu.pagerduty.com"
        )

    def _test_api_key_and_fetch_user_data(self, api_key, api_base_url):
        """Test the API key and fetch abilities to validate roles."""
        session = RestApiV2Client(api_key)
        session.url = api_base_url
        try:
            abilities = session.rget("/abilities")
            _LOGGER.debug(f"Available roles: {abilities}")

            # for future role check discovery
            # if not self._validate_user_roles(abilities):
            #     raise PDClientError("User does not have required roles")
            user = session.rget("/users/me", params={"include[]": "teams"})
            _LOGGER.debug(f"User {user}")
            return True, {"user": user}

        except Error:
            return False, {}

    def _validate_user_roles(self, abilities):
        """Check if user has the required roles based on abilities."""
        processed_abilities = set()

        for ability in abilities:
            base_ability = ability.replace(".read", "")
            processed_abilities.add(base_ability)

        return any(role in processed_abilities for role in REQUIRED_ROLES)


class PagerDutyOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for PagerDuty integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Get current values from options or fall back to data for migration
        current_template = self.config_entry.options.get(
            "extra_incident_attributes_template",
            self.config_entry.data.get("extra_incident_attributes_template", "")
        )
        current_email = self.config_entry.options.get(
            "default_from_email",
            self.config_entry.data.get("default_from_email", "")
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "extra_incident_attributes_template",
                        default=current_template
                    ): TemplateSelector(),
                    vol.Optional(
                        "default_from_email",
                        default=current_email
                    ): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.EMAIL)
                    ),
                }
            ),
        )
