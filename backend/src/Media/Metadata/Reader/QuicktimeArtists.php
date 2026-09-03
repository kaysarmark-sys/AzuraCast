<?php

declare(strict_types=1);

namespace App\Media\Metadata\Reader;

/** Read repeated iTunes artist atoms without loading audio data into memory. */
final class QuicktimeArtists
{
    public static function read(string $path): array
    {
        $file = fopen($path, 'rb');
        if (false === $file) {
            return [];
        }
        try {
            $artists = [];
            self::boxes($file, (int)fstat($file)['size'], 0, false, $artists);
            return array_values(array_unique($artists));
        } finally {
            fclose($file);
        }
    }

    private static function boxes($file, int $end, int $depth, bool $artist, array &$artists): void
    {
        if ($depth > 8) {
            return;
        }
        while (ftell($file) + 8 <= $end) {
            $start = ftell($file);
            $header = fread($file, 8);
            if (strlen($header) !== 8) {
                return;
            }
            $size = unpack('N', substr($header, 0, 4))[1];
            $type = substr($header, 4, 4);
            $headerSize = 8;
            if ($size === 1) {
                $extended = fread($file, 8);
                if (strlen($extended) !== 8) {
                    return;
                }
                $parts = unpack('Nhigh/Nlow', $extended);
                $size = $parts['high'] * 4294967296 + $parts['low'];
                $headerSize = 16;
            } elseif ($size === 0) {
                $size = $end - $start;
            }
            if ($size < $headerSize || $size > $end - $start) {
                return;
            }
            $next = $start + $size;
            if ($artist && $type === 'data' && $size >= $headerSize + 8 && $size < 1048576) {
                $value = fread($file, $size - $headerSize);
                $encoding = unpack('N', substr($value, 0, 4))[1] & 0xffffff;
                $text = substr($value, 8);
                if ($encoding === 2) {
                    $text = mb_convert_encoding($text, 'UTF-8', 'UTF-16BE');
                }
                if (in_array($encoding, [1, 2], true) && trim($text) !== '') {
                    $artists[] = trim($text);
                }
            } elseif (in_array($type, ['moov', 'udta', 'meta', 'ilst', "\xa9ART"], true)) {
                if ($type === 'meta') {
                    fseek($file, 4, SEEK_CUR);
                }
                self::boxes($file, $next, $depth + 1, $type === "\xa9ART", $artists);
            }
            fseek($file, $next);
        }
    }
}
