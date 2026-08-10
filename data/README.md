Ce dossier est créé et peuplé automatiquement par l'application au runtime :

```
data/clients/index.json                          liste des clients
data/clients/<client_id>/mappings.json            référentiel du client
data/clients/<client_id>/history/index.jsonl      journal des conversions
data/clients/<client_id>/history/files/           fichiers source + générés archivés
```

`data/clients/` est volontairement exclu du dépôt git (`.gitignore`) : il
contient des données comptables/financières de clients réels et ne doit
jamais être versionné. Sur un serveur dédié, prévoir un disque persistant
(et une politique de sauvegarde) pointant vers ce dossier.
