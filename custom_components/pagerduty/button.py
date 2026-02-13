"""Button platform for PagerDuty integration."""
import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er
from homeassistant.core import callback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up PagerDuty button entities from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    session = hass.data[DOMAIN][entry.entry_id]["session"]
    default_from_email = entry.data.get("default_from_email", "")

    # Get entity registry to clean up orphaned entities from previous sessions
    entity_reg = er.async_get(hass)
    
    # Get all existing PagerDuty acknowledge button entities
    existing_entities = er.async_entries_for_config_entry(
        entity_reg, entry.entry_id
    )
    existing_button_entities = {
        entity.unique_id: entity
        for entity in existing_entities
        if entity.unique_id and entity.unique_id.startswith("pagerduty_ack_")
    }
    
    # Get current triggered incidents to determine which buttons should exist
    incidents = coordinator.data.get("incidents", [])
    current_triggered_ids = {
        f"pagerduty_ack_{incident.get('id')}"
        for incident in incidents
        if incident.get("status") == "triggered"
    }
    
    # Clean up orphaned entities from previous sessions
    for unique_id, entity in existing_button_entities.items():
        if unique_id not in current_triggered_ids:
            _LOGGER.debug(
                "Removing orphaned button entity %s from previous session",
                unique_id
            )
            entity_reg.async_remove(entity.entity_id)

    # Track existing button entities
    tracked_buttons = {}

    @callback
    def async_add_remove_buttons():
        """Add buttons for triggered incidents and remove for non-triggered."""
        incidents = coordinator.data.get("incidents", [])
        triggered_incident_ids = set()

        # Find all triggered incidents
        for incident in incidents:
            if incident.get("status") == "triggered":
                incident_id = incident.get("id")
                triggered_incident_ids.add(incident_id)

                # Add button if it doesn't exist
                if incident_id not in tracked_buttons:
                    button = PagerDutyAcknowledgeButton(
                        coordinator, session, incident, default_from_email
                    )
                    tracked_buttons[incident_id] = button
                    async_add_entities([button], True)
                    _LOGGER.debug(
                        "Added acknowledge button for incident %s",
                        incident_id
                    )

        # Remove buttons for incidents that are no longer triggered
        for incident_id in list(tracked_buttons.keys()):
            if incident_id not in triggered_incident_ids:
                button = tracked_buttons.pop(incident_id)
                # Mark the button for removal with force_remove to clean up registry
                hass.async_create_task(button.async_remove(force_remove=True))
                _LOGGER.debug(
                    "Removed acknowledge button for incident %s",
                    incident_id
                )

    # Initial setup
    async_add_remove_buttons()

    # Register callback for coordinator updates
    unsub = coordinator.async_add_listener(async_add_remove_buttons)

    # Store the unsubscribe function for cleanup
    hass.data[DOMAIN][entry.entry_id]["button_unsub"] = unsub


class PagerDutyAcknowledgeButton(ButtonEntity, CoordinatorEntity):
    """Button entity to acknowledge a PagerDuty incident."""

    def __init__(self, coordinator, session, incident, default_from_email):
        """Initialize the button."""
        super().__init__(coordinator)
        self._session = session
        self._incident_id = incident.get("id")
        self._incident_number = incident.get("incident_number")
        self._incident_title = incident.get("title", "Unknown")
        self._service_name = incident.get("service", {}).get("summary", "Unknown")
        self._default_from_email = default_from_email

        self._attr_name = f"Acknowledge Incident #{self._incident_number}"
        self._attr_unique_id = f"pagerduty_ack_{self._incident_id}"

        _LOGGER.debug(
            "Initialized acknowledge button for incident %s",
            self._incident_id
        )

    @property
    def device_info(self):
        """Return device info for linking this entity to the unique PagerDuty device."""
        unique_device_name = f"PagerDuty_{self.coordinator.data.get('user_id', 'default_user_id')}"
        return {
            "identifiers": {(DOMAIN, unique_device_name)},
            "name": unique_device_name,
            "manufacturer": "PagerDuty Inc.",
        }

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        return {
            "incident_id": self._incident_id,
            "incident_number": self._incident_number,
            "incident_title": self._incident_title,
            "service_name": self._service_name,
        }

    @property
    def available(self):
        """Return if entity is available."""
        # Check if incident still exists and is triggered
        incidents = self.coordinator.data.get("incidents", [])
        for incident in incidents:
            if incident.get("id") == self._incident_id:
                return incident.get("status") == "triggered"
        return False

    async def async_press(self):
        """Handle the button press - acknowledge the incident."""
        _LOGGER.info(
            "Acknowledging PagerDuty incident %s",
            self._incident_id
        )

        try:
            await self.hass.async_add_executor_job(
                self._acknowledge_incident
            )
            _LOGGER.info(
                "Successfully acknowledged incident %s",
                self._incident_id
            )

            # Request a coordinator refresh to update the state
            await self.coordinator.async_request_refresh()

        except Exception as e:
            _LOGGER.error(
                "Failed to acknowledge incident %s: %s",
                self._incident_id,
                e
            )
            raise

    def _acknowledge_incident(self):
        """Acknowledge the incident via PagerDuty API."""
        incident_url = f"/incidents/{self._incident_id}"

        headers = {}
        if self._default_from_email:
            headers["From"] = self._default_from_email

        # Update incident status to acknowledged
        self._session.rput(
            incident_url,
            json={
                "type": "incident",
                "status": "acknowledged",
            },
            headers=headers,
        )
