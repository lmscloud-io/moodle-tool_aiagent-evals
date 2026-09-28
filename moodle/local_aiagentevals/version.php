<?php
// This file is part of the evaluation harness for tool_aiagent. It is installed only on disposable
// evaluation sites and never shipped.

/**
 * Version details.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    https://lmscloud.io/products/ai-agent/license LMSCloud Commercial License
 */

defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_aiagentevals';
$plugin->version = 2026092800;
$plugin->requires = 2024100700;
$plugin->maturity = MATURITY_ALPHA;
$plugin->release = '0.1';
$plugin->dependencies = ['tool_aiagent' => ANY_VERSION];
