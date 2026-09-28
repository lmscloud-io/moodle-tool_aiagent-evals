<?php
// This file is part of the evaluation harness for tool_aiagent. It is installed only on disposable
// evaluation sites and never shipped.

/**
 * Check an evaluation site is ready: the AI agent's license is valid and every material bundle is on disk.
 *
 * Prints {"ok": bool, "problems": [...]} and exits with 1 when the site is not ready. Without the
 * materials the built-in functions disappear silently, which would look like every model failing.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    https://lmscloud.io/products/ai-agent/license LMSCloud Commercial License
 */

define('CLI_SCRIPT', true);

require(__DIR__ . '/../../../config.php');

$problems = [];

// Prefer the plugin's own answers; the fallbacks cover a build that renamed these classes.
$licenseclass = '\tool_aiagent\local\api\license';
if (class_exists($licenseclass)) {
    if (!$licenseclass::is_valid()) {
        $problems[] = 'The AI agent license is not valid.';
    }
} else if (!get_config('tool_aiagent', 'apikey')) {
    $problems[] = 'The AI agent license was never activated (no site API key).';
}

$storeclass = '\tool_aiagent\local\api\cloud_store';
$bundles = class_exists($storeclass)
    ? $storeclass::EXPECTED_BUNDLES
    : ['tools', 'corrections', 'metadata', 'skills', 'instructions', 'overridemap'];
$folder = $CFG->dataroot . '/tool_aiagent/cloud';
foreach ($bundles as $bundle) {
    if (!is_readable($folder . '/' . $bundle . '.json')) {
        $problems[] = "The material bundle '{$bundle}' is missing from {$folder}.";
    }
}

echo json_encode(['ok' => !$problems, 'problems' => $problems]) . "\n";
exit($problems ? 1 : 0);
