# Transfer dir permissions

Ingest moves clips out of `/mnt/os-shared/transfer/clips`, which requires `dev`
to have write permission on that directory. It's granted via the shared
`developers` group:

```bash
chgrp -R developers /mnt/os-shared/transfer
chmod -R g+w        /mnt/os-shared/transfer
find /mnt/os-shared/transfer -type d -exec chmod g+s {} +
```

## Caveat

A Windows-side process that rewrites these files may reset ownership back to
`ethan`-only, at which point ingest fails again with a `PermissionError` on
delete. Re-run the three commands above after big transfers to restore it.

If this becomes a recurring nuisance, the durable fix is a mount-option change
(forcing `gid=developers` in the mount/fstab), which needs root.
