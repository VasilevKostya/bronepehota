<?php
// Verify the real Flarum policies with unsaved role fixtures; no users are created.
require '/var/www/html/vendor/autoload.php';
$app = (require '/var/www/html/site.php')->bootApp();
$app->getContainer();

use Flarum\Group\Group;
use Flarum\Tags\Tag;
use Flarum\User\Guest;
use Flarum\User\User;
use Illuminate\Database\Eloquent\Collection;

$member = new User;
$member->id = -100;
$member->is_email_confirmed = true;
$member->setRelation('groups', new Collection);
$moderator = new User;
$moderator->id = -101;
$moderator->is_email_confirmed = true;
$moderator->setRelation('groups', new Collection([Group::findOrFail(4)]));
$actors = ['guest' => new Guest, 'member' => $member,
           'moderator' => $moderator, 'administrator' => User::findOrFail(1)];
$count = 0;
foreach (['rules-questions', 'suggestions', 'announcements'] as $slug) {
    $tag = Tag::where('slug', $slug)->firstOrFail();
    foreach ($actors as $role => $actor) {
        $actual = ['view' => $actor->can('viewForum', $tag),
                   'start' => $actor->can('startDiscussion', $tag),
                   'reply' => $actor->can('discussion.reply', $tag)];
        $expected = ['view' => true,
                     'start' => $role !== 'guest' && !($role === 'member' && $slug === 'announcements'),
                     'reply' => $role !== 'guest'];
        if ($actual !== $expected) {
            throw new RuntimeException(json_encode(compact('slug', 'role', 'expected', 'actual')));
        }
        $count += count($actual);
        echo $slug, ' / ', $role, ': OK', PHP_EOL;
    }
}
echo $count, ' policy checks passed; no test accounts were persisted.', PHP_EOL;
