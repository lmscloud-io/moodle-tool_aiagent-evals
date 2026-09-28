<?php
// This file is part of the evaluation harness for tool_aiagent. It is installed only on disposable
// evaluation sites and never shipped.

/**
 * Print the tool_aiagent_usage rows of one chat as JSON: php usage.php --hash=<chat hash>.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    https://lmscloud.io/products/ai-agent/license LMSCloud Commercial License
 */

define('CLI_SCRIPT', true);

require(__DIR__ . '/../../../config.php');
require_once($CFG->libdir . '/clilib.php');

[$options] = cli_get_params(['hash' => ''], []);
$hash = clean_param($options['hash'], PARAM_ALPHANUMEXT);
$conversationid = $hash === '' ? false : $DB->get_field('tool_aiagent_conversation', 'id', ['hash' => $hash]);
if (!$conversationid) {
    cli_error('No chat has that hash.');
}

$rows = [];
foreach ($DB->get_records('tool_aiagent_usage', ['conversationid' => $conversationid], 'id ASC') as $row) {
    $rows[] = [
        'messageid' => $row->messageid === null ? null : (int) $row->messageid,
        'provider' => (string) $row->provider,
        'model' => (string) $row->model,
        'prompttokens' => $row->prompttokens === null ? null : (int) $row->prompttokens,
        'completiontokens' => $row->completiontokens === null ? null : (int) $row->completiontokens,
        'success' => (bool) $row->success,
        'metadata' => json_decode((string) $row->metadata, true),
        'timecreated' => (int) $row->timecreated,
    ];
}
echo json_encode($rows) . "\n";
