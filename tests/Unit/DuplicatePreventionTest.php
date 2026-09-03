<?php

declare(strict_types=1);

namespace Unit;

use App\Entity\Api\StationPlaylistQueue;
use App\Radio\AutoDJ\DuplicatePrevention;
use App\Tests\Module;
use Codeception\Test\Unit;
use UnitTester;

class DuplicatePreventionTest extends Unit
{
    protected DuplicatePrevention $duplicatePrevention;

    protected function _inject(Module $testsModule): void
    {
        $di = $testsModule->container;
        $this->duplicatePrevention = $di->get(DuplicatePrevention::class);
    }

    public function testDistinctTracks(): void
    {
        $eligibleTrack = new StationPlaylistQueue();
        $eligibleTrack->artist = 'Foo Fighters feat. AzuraCast Testers';
        $eligibleTrack->title = 'Best of You';
        $eligibleTracks = [$eligibleTrack];

        $fullDuplicateTest = [
            [
                'song_id' => 'best_of_you_foo_fighters',
                'text' => 'Foo Fighters - Best of You',
                'artist' => 'Foo Fighters',
                'title' => 'Best of You',
                'timestamp_played' => 0,
            ],
        ];
        $fullDuplicateResult = $this->duplicatePrevention->getDistinctTrack($eligibleTracks, $fullDuplicateTest);
        $this->assertNull($fullDuplicateResult);

        $artistDuplicateTest = [
            [
                'song_id' => 'everlong_foo_fighters',
                'text' => 'Foo Fighters - Everlong',
                'artist' => 'Foo Fighters',
                'title' => 'Everlong',
                'timestamp_played' => 0,
            ],
        ];
        $artistDuplicateResult = $this->duplicatePrevention->getDistinctTrack($eligibleTracks, $artistDuplicateTest);
        $this->assertNull($artistDuplicateResult);

        $partialDuplicateTest = [
            [
                'song_id' => 'testing_song_foo_fighters_feat_fall_out_boy',
                'text' => 'Foo Fighters feat. Fall Out Boy - Testing Song',
                'artist' => 'Foo Fighters feat. Fall Out Boy',
                'title' => 'Testing Song',
                'timestamp_played' => 0,
            ],
        ];
        $partialDuplicateResult = $this->duplicatePrevention->getDistinctTrack($eligibleTracks, $partialDuplicateTest);
        $this->assertNull($partialDuplicateResult);

        $noDuplicatesTest = [
            [
                'song_id' => 'testing_song_1_panic_at_the_disco',
                'text' => 'Panic! at the Disco - Testing Song 1',
                'artist' => 'Panic! at the Disco',
                'title' => 'Testing Song 1',
                'timestamp_played' => 0,
            ],
            [
                'song_id' => 'lost_memory_sakujo',
                'text' => '削除 - Lost Memory',
                'artist' => '削除',
                'title' => 'Lost Memory',
                'timestamp_played' => 0,
            ],
        ];
        $noDuplicatesResult = $this->duplicatePrevention->getDistinctTrack($eligibleTracks, $noDuplicatesTest);
        $this->assertNotNull($noDuplicatesResult);
    }
    public function testArtistSeparatorsAndIndependentWindows(): void
    {
        $candidate = new StationPlaylistQueue();
        $candidate->media_id = 1;
        $candidate->song_id = 'new-song';
        $candidate->title = 'New Song';
        $now = new \DateTimeImmutable('@10000');
        $history = [['song_id' => 'old-song', 'title' => 'Old Song', 'artist' => 'Artist B',
            'timestamp_played' => 9400, 'is_played' => true]];
        foreach (['Artist B', 'Artist A,Artist B', 'Artist A & ARTIST B', 'Artist A&Artist B,Artist C', 'Artist A; Artist B'] as $artists) {
            $candidate->artist = $artists;
            $recent = $this->duplicatePrevention->applyTimeRanges($history, $now, 5, 20);
            $this->assertNull($this->duplicatePrevention->preventDuplicates([$candidate], $recent));
            $expired = $this->duplicatePrevention->applyTimeRanges($history, $now, 20, 5);
            $this->assertSame($candidate, $this->duplicatePrevention->preventDuplicates([$candidate], $expired));
        }
        $candidate->artist = 'Artist B';
        $disabled = $this->duplicatePrevention->applyTimeRanges($history, $now, 20, 0);
        $this->assertSame($candidate, $this->duplicatePrevention->preventDuplicates([$candidate], $disabled));
        $candidate->title = 'Old Song';
        $this->assertNull($this->duplicatePrevention->preventDuplicates([$candidate], $disabled));
        $candidate->title = 'New Song';
        $history[0]['is_played'] = false;
        $queued = $this->duplicatePrevention->applyTimeRanges($history, $now, 5, 5);
        $this->assertNull($this->duplicatePrevention->preventDuplicates([$candidate], $queued));
        $this->assertSame($candidate, $this->duplicatePrevention->preventDuplicates([$candidate], $queued, true));
        $candidate->artist = 'Artist Bee';
        $this->assertSame($candidate, $this->duplicatePrevention->preventDuplicates([$candidate], $queued));
    }
    public function testJustinBieberCollaborations(): void
    {
        $candidate = new StationPlaylistQueue();
        $candidate->artist = 'Justin Bieber, Nicki Minaj';
        $candidate->title = 'Beauty And A Beat';
        $history = [['artist' => 'Justin Bieber; Ludacris', 'title' => 'Baby',
            'song_id' => 'baby', 'timestamp_played' => 8800]];
        $history = $this->duplicatePrevention->applyTimeRanges($history, new \DateTimeImmutable('@10000'), 120, 120);
        $this->assertNull($this->duplicatePrevention->getDistinctTrack([$candidate], $history));
    }
}
