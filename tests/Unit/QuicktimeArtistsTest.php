<?php

declare(strict_types=1);
namespace Unit;

use App\Media\Metadata\Reader\QuicktimeArtists;
use Codeception\Test\Unit;

final class QuicktimeArtistsTest extends Unit
{
    public function testRepeatedArtistAtoms(): void
    {
        $box = static fn(string $type, string $data) => pack('N', strlen($data) + 8) . $type . $data;
        $artists = '';
        foreach (['Justin Bieber', 'Ludacris', 'Third Artist', 'Justin Bieber'] as $name) {
            $artists .= $box("\xa9ART", $box('data', pack('NN', 1, 0) . $name));
        }
        $file = tempnam(sys_get_temp_dir(), 'artist-test');
        try {
            file_put_contents($file, $box('ftyp', 'M4A ') . $box('mdat', str_repeat('x', 128)) .
                $box('moov', $box('udta', $box('meta', pack('N', 0) . $box('ilst', $artists)))));
            $this->assertSame(['Justin Bieber', 'Ludacris', 'Third Artist'], QuicktimeArtists::read($file));
            file_put_contents($file, pack('N', 999999) . 'moov');
            $this->assertSame([], QuicktimeArtists::read($file));
        } finally {
            unlink($file);
        }
    }
}
