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
 * Seed an evaluation site from a profile and print the manifest: php seed.php --profile=standard.
 *
 * A site is seeded once; later calls print the manifest stored by the first, so the harness can ask again
 * on a site it reuses. The data comes from core's data generators, which work on any site.
 *
 * @package    local_aiagentevals
 * @copyright  LMSCloud Limited <info@lmscloud.io>
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

define('CLI_SCRIPT', true);

require(__DIR__ . '/../../../config.php');
require_once($CFG->libdir . '/clilib.php');
require_once($CFG->libdir . '/testing/generator/lib.php');

/**
 * Usernames named by a profile entry: a list, or a range written as "student01-student12".
 *
 * @param array|string $spec The entry.
 * @return string[] The usernames.
 */
function local_aiagentevals_usernames($spec): array {
    if (is_array($spec)) {
        return array_values($spec);
    }
    if (!preg_match('/^([a-z]+)(\d+)-\1(\d+)$/', (string) $spec, $matches)) {
        cli_error("Cannot read the user list '{$spec}'.");
    }
    $names = [];
    for ($number = (int) $matches[2]; $number <= (int) $matches[3]; $number++) {
        $names[] = $matches[1] . str_pad((string) $number, strlen($matches[2]), '0', STR_PAD_LEFT);
    }
    return $names;
}

[$options] = cli_get_params(['profile' => 'standard'], []);

$stored = get_config('local_aiagentevals', 'manifest');
if ($stored) {
    echo $stored . "\n";
    exit(0);
}

$profilename = clean_param($options['profile'], PARAM_ALPHANUMEXT);
$profilefile = __DIR__ . "/../profiles/{$profilename}.json";
$profile = is_readable($profilefile) ? json_decode(file_get_contents($profilefile), true) : null;
if (!is_array($profile)) {
    cli_error("No seed profile called '{$profilename}'.");
}

\core\session\manager::set_user(get_admin());
$generator = new testing_data_generator();
$systemcontextid = context_system::instance()->id;
$manifest = ['password' => (string) $profile['password'], 'users' => [], 'courses' => [], 'groups' => []];

$categories = [];
foreach ($profile['categories'] as $category) {
    $record = $generator->create_category(['name' => $category['name'], 'idnumber' => $category['idnumber']]);
    $categories[$category['idnumber']] = $record->id;
}

foreach ($profile['courses'] as $course) {
    $record = $generator->create_course([
        'shortname' => $course['shortname'],
        'fullname' => $course['fullname'],
        'category' => $categories[$course['category']],
    ]);
    $manifest['courses'][$course['shortname']] = [
        'id' => (int) $record->id,
        'contextid' => (int) context_course::instance($record->id)->id,
        'url' => (new moodle_url('/course/view.php', ['id' => $record->id]))->out(false),
    ];
}

$users = $profile['users'];
$students = $profile['students'];
for ($number = 1; $number <= (int) $students['count']; $number++) {
    $suffix = str_pad((string) $number, 2, '0', STR_PAD_LEFT);
    $users[] = [
        'username' => $students['prefix'] . $suffix,
        'firstname' => $students['firstname'],
        'lastname' => $students['lastnameprefix'] . ' ' . $suffix,
    ];
}
foreach ($users as $user) {
    $record = $generator->create_user([
        'username' => $user['username'],
        'password' => $manifest['password'],
        'firstname' => $user['firstname'],
        'lastname' => $user['lastname'],
        'email' => $user['username'] . '@example.com',
    ]);
    $manifest['users'][$user['username']] = (int) $record->id;
    if (!empty($user['systemrole'])) {
        $roleid = $DB->get_field('role', 'id', ['shortname' => $user['systemrole']], MUST_EXIST);
        role_assign($roleid, $record->id, $systemcontextid);
    }
}

foreach ($profile['enrolments'] as $enrolment) {
    $courseid = $manifest['courses'][$enrolment['course']]['id'];
    foreach (local_aiagentevals_usernames($enrolment['users']) as $username) {
        $generator->enrol_user($manifest['users'][$username], $courseid, $enrolment['role']);
    }
}

foreach ($profile['groups'] as $group) {
    $record = $generator->create_group([
        'courseid' => $manifest['courses'][$group['course']]['id'],
        'name' => $group['name'],
    ]);
    foreach (local_aiagentevals_usernames($group['members']) as $username) {
        $generator->create_group_member(['groupid' => $record->id, 'userid' => $manifest['users'][$username]]);
    }
    $manifest['groups'][$group['course'] . '/' . $group['name']] = (int) $record->id;
}

// Grant what a customer would: only managers can chat by default.
foreach ($profile['capabilities'] as $grant) {
    $roleid = $DB->get_field('role', 'id', ['shortname' => $grant['role']], MUST_EXIST);
    assign_capability($grant['capability'], CAP_ALLOW, $roleid, $systemcontextid, true);
}

\cache_helper::purge_all();
$json = json_encode($manifest);
set_config('manifest', $json, 'local_aiagentevals');
echo $json . "\n";
