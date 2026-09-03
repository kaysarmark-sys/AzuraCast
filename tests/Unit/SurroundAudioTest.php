<?php

declare(strict_types=1);

namespace Unit;

use App\Entity\StationBackendConfiguration;
use App\Radio\Backend\Liquidsoap\ConfigWriter;
use App\Radio\Backend\Liquidsoap\EncodingFormat;
use App\Radio\Enums\AudioProcessingMethods;
use App\Radio\Enums\HlsStreamProfiles;
use App\Radio\Enums\StreamFormats;
use Codeception\Test\Unit;
use ReflectionClass;
use ReflectionMethod;

final class SurroundAudioTest extends Unit
{
    public function testStationSettingRoundTripAndDefaults(): void
    {
        $config = new StationBackendConfiguration();
        self::assertSame(2, $config->audio_channels);
        self::assertFalse($config->shouldShareEncoders());

        $config->audio_channels = '6';
        $config->audio_processing_method = AudioProcessingMethods::MasterMe;
        $restored = new StationBackendConfiguration($config->toArray(true) ?? []);
        self::assertSame(6, $restored->audio_channels);
        self::assertTrue($restored->shouldShareEncoders());
        self::assertFalse($restored->isAudioProcessingEnabled());

        $restored->audio_channels = 2;
        self::assertTrue($restored->isAudioProcessingEnabled());
        self::assertFalse($restored->shouldShareEncoders());
        $restored->audio_channels = 8;
        self::assertSame(2, $restored->audio_channels);
    }

    public function testSurroundEncodersAndStereoCompatibility(): void
    {
        $writer = new ReflectionClass(ConfigWriter::class)->newInstanceWithoutConstructor();
        $method = new ReflectionMethod(ConfigWriter::class, 'getFfmpegAudioString');

        foreach ([StreamFormats::Aac, StreamFormats::Ogg, StreamFormats::Opus, StreamFormats::Flac] as $format) {
            $encoding = new EncodingFormat($format, 320, HlsStreamProfiles::AacHighEfficiencyV2);
            $surround = $method->invoke($writer, $encoding, 6);
            $stereo = $method->invoke($writer, $encoding, 2);
            self::assertStringContainsString('channels=6', $surround);
            self::assertStringContainsString('channels=2', $stereo);

            if ($format === StreamFormats::Aac) {
                self::assertStringContainsString('profile="aac_low"', $surround);
                self::assertStringContainsString('profile="aac_he_v2"', $stereo);
            }
            if ($format === StreamFormats::Opus) {
                self::assertStringContainsString('mapping_family=1', $surround);
                self::assertStringNotContainsString('mapping_family', $stereo);
            }
        }

        $mp3 = new EncodingFormat(StreamFormats::Mp3, 128);
        self::assertStringContainsString('%audio.raw(', $method->invoke($writer, $mp3, 6));
        self::assertStringContainsString('ac=2', $method->invoke($writer, $mp3, 6));
        self::assertStringNotContainsString('%audio.raw(', $method->invoke($writer, $mp3, 2));
    }
}
