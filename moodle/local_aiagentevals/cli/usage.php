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
 * Print the tool_aiagent_usage rows of one chat as JSON: php usage.php --hash=<chat hash>.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
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
