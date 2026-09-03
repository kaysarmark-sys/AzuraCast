<?php

declare(strict_types=1);

use App\Radio\Backend\Liquidsoap\ConfigWriter;
use App\Radio\Backend\Liquidsoap\EncodingFormat;
use App\Radio\Enums\HlsStreamProfiles;
use App\Radio\Enums\StreamFormats;

require dirname(__DIR__) . '/vendor/autoload.php';

$writer = new ReflectionClass(ConfigWriter::class)->newInstanceWithoutConstructor();
$method = new ReflectionMethod(ConfigWriter::class, 'getFfmpegAudioString');
$encoders = [];
foreach (StreamFormats::cases() as $format) {
    $encoding = new EncodingFormat($format, 320, HlsStreamProfiles::AacHighEfficiencyV2);
    $encoders[$format->value] = [
        'audio' => $method->invoke($writer, $encoding, 6),
        'container' => $format->getFfmpegContainer(),
    ];
}
echo json_encode($encoders, JSON_THROW_ON_ERROR);
