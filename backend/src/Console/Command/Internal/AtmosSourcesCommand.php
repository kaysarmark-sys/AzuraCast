<?php

declare(strict_types=1);

namespace App\Console\Command\Internal;

use App\Console\Command\CommandAbstract;
use App\Entity\Station;
use Doctrine\ORM\EntityManagerInterface;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

#[AsCommand(name: 'azuracast:internal:atmos-sources', description: 'Local Atmos worker source snapshot.')]
final class AtmosSourcesCommand extends CommandAbstract
{
    public function __construct(private readonly EntityManagerInterface $em)
    {
        parent::__construct();
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        do {
            $this->em->clear();
            $output->writeln(json_encode($this->getSources(), JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES));
            flush();
            if (!$input->getOption('watch')) {
                break;
            }
            sleep(2);
        } while (true);
        return 0;
    }

    protected function configure(): void
    {
        $this->addOption('watch', null, InputOption::VALUE_NONE, 'Emit a snapshot every two seconds.');
    }

    private function getSources(): array
    {
        $sources = [];
        foreach ($this->em->getRepository(Station::class)->findAll() as $station) {
            if (!$station->is_enabled || !$station->enable_hls || !$station->backend_config->hls_atmos) {
                continue;
            }
            $song = $station->current_song;
            $media = $song?->media;
            $path = null;
            if (!$station->is_streamer_live && $media?->storage_location->adapter->isLocal()) {
                $root = realpath($media->storage_location->getFilteredPath());
                $candidate = realpath($root . '/' . $media->path);
                if ($root && $candidate && str_starts_with($candidate, $root . '/') && is_file($candidate)) {
                    $path = $candidate;
                }
            }
            $isLive = null === $path;
            $sources[] = [
                'id' => $station->id,
                'output' => $station->getRadioHlsDir() . '/atmos',
                'work' => $station->getRadioTempDir() . '/atmos',
                'key' => $isLive ? 'live' : (string)$song->id,
                'start' => $isLive ? null : (float)$song->timestamp_start->format('U.u'),
                'path' => $path ?? $station->getRadioHlsDir() . '/live.m3u8',
                'live' => $isLive,
                'cue' => $isLive ? 0 : max(0, $media->extra_metadata->cue_in ?? 0),
                'duration' => $isLive ? null : $media->getCalculatedLength(),
            ];
        }
        return $sources;
    }
}
