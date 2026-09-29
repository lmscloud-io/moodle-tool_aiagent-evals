<?php
// This file is part of Moodle - https://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <https://www.gnu.org/licenses/>.

/**
 * Make one matrix cell the site's only AI provider for generating text.
 *
 * Reads the cell as JSON on stdin, so API keys never appear in process arguments:
 *   {"id": "...", "provider": "aiprovider_openai", "config": {...}, "action": {...}, "plugin_settings": {...}}
 * With --status, prints {"enabled": [components], "settings": {...}} instead.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

define('CLI_SCRIPT', true);

require(__DIR__ . '/../../../config.php');
require_once($CFG->libdir . '/clilib.php');

use core_ai\aiactions\generate_text;

[$options] = cli_get_params(['status' => false], []);

$manager = \core\di::get(\core_ai\manager::class);

if ($options['status']) {
    $enabled = [];
    $providers = $manager->get_providers_for_actions([generate_text::class], true);
    foreach ($providers[generate_text::class] ?? [] as $provider) {
        $enabled[] = explode('\\', get_class($provider))[0];
    }
    echo json_encode([
        'enabled' => $enabled,
        'settings' => [
            'openai_api_type' => get_config('tool_aiagent', 'openai_api_type'),
            'gemini_api_type' => get_config('tool_aiagent', 'gemini_api_type'),
        ],
    ]) . "\n";
    exit(0);
}

$cell = json_decode(stream_get_contents(STDIN), true);
if (!is_array($cell) || empty($cell['provider'])) {
    cli_error('Expected a cell as JSON on stdin.');
}
$component = clean_param($cell['provider'], PARAM_COMPONENT);
if (!\core_component::get_component_directory($component)) {
    cli_error("{$component} is not installed on this site.");
}
$config = (array) ($cell['config'] ?? []);
$action = (array) ($cell['action'] ?? []);
$shortname = preg_replace('/^aiprovider_/', '', $component);

if (method_exists($manager, 'create_provider_instance')) {
    // Moodle 5.0+: one instance per cell, named after it; every other instance is disabled.
    $name = 'evals-' . clean_param((string) ($cell['id'] ?? $shortname), PARAM_ALPHANUMEXT);
    $actionconfig = [generate_text::class => ['enabled' => true, 'settings' => $action]];
    $target = null;
    foreach ($manager->get_provider_instances() as $instance) {
        if ($instance->name === $name) {
            $target = $instance;
        } else {
            $manager->disable_provider_instance($instance);
        }
    }
    if ($target === null) {
        $manager->create_provider_instance('\\' . $component . '\\provider', $name, true, $config, $actionconfig);
    } else {
        $target = $manager->update_provider_instance($target, $config, $actionconfig);
        $manager->enable_provider_instance($target);
    }
} else {
    // Moodle 4.5: provider settings are plugin config, and only this provider plugin stays enabled.
    foreach (\core\plugininfo\aiprovider::get_enabled_plugins() ?? [] as $enabledname) {
        if ($enabledname !== $shortname) {
            \core\plugininfo\aiprovider::enable_plugin($enabledname, 0);
        }
    }
    foreach ($config as $key => $value) {
        set_config($key, $value, $component);
    }
    foreach ($action as $key => $value) {
        set_config('action_generate_text_' . $key, $value, $component);
    }
    \core\plugininfo\aiprovider::enable_plugin($shortname, 1);
    \core_ai\manager::set_action_state($component, 'generate_text', 1);
}

foreach ((array) ($cell['plugin_settings'] ?? []) as $setting => $value) {
    set_config(clean_param($setting, PARAM_ALPHANUMEXT), (string) $value, 'tool_aiagent');
}
\cache_helper::purge_all();
echo json_encode(['activated' => $cell['id'] ?? $component]) . "\n";
