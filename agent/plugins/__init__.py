from agent.plugins.builder_plugin import BuilderPlugin
from agent.plugins.web_media_plugin import WebMediaPlugin
from agent.plugins.messaging_schedule_plugin import MessagingSchedulePlugin
from agent.plugins.life_memory_plugin import LifeMemoryPlugin
from agent.plugins.vision_iot_mode_plugin import VisionIoTModePlugin
from agent.plugins.youtube_plugin import YouTubePlugin
from agent.plugins.mcp_bridge_plugin import MCPClientBridgePlugin

# Backward-compatible aliases so any existing import in jev_router.py succeeds:
MCPBridgePlugin = MCPClientBridgePlugin
YouTubeStagedPlugin = YouTubePlugin
