# Collection Postman pour l'API Externe

Ce répertoire contient les collections Postman pour tester les endpoints externes de l'API Aigle.

## Démarrage Rapide

### 1. Importer la Collection
Importez `external-api.postman_collection.json` dans Postman.

### 2. Configurer les Variables d'Environnement
La collection utilise deux variables à configurer :

- **`base_url`**: URL de base de l'API (par défaut: `http://localhost:8000`)
- **`api_key`**: Votre clé API pour l'authentification

#### Option A: Modifier les Variables de Collection
1. Dans Postman, cliquez sur le nom de la collection
2. Allez dans l'onglet "Variables"
3. Mettez à jour la valeur de `api_key` avec votre clé API réelle

#### Option B: Créer un Environnement Postman
1. Créez un nouvel environnement dans Postman
2. Ajoutez les variables :
   - `base_url` = `http://localhost:8000` | `https://preprod.api.aigle.beta.gouv.fr` | `https://api.aigle.beta.gouv.fr`
   - `api_key` = `VOTRE_CLE_API_ICI`
3. Sélectionnez l'environnement avant d'exécuter les requêtes

## Endpoints Disponibles

### 1. Test GET - Vérification d'Authentification
**Endpoint:** `GET /api/external/test/`

Endpoint simple pour vérifier que l'authentification par clé API fonctionne.

**Réponse:**
```json
{
  "message": "Successfully authenticated with API key",
  "status": "success",
  "data": {
    "timestamp": "2024-01-15T10:30:00.123456"
  }
}
```

### 2. Test POST - Echo de Données
**Endpoint:** `POST /api/external/test/`

Endpoint de test qui renvoie les données reçues.

**Requête:**
```json
{
  "test_field": "test_value",
  "number": 123,
  "nested": {
    "key": "value"
  }
}
```

**Réponse:**
```json
{
  "message": "Data received successfully",
  "status": "success",
  "received_data": {
    "test_field": "test_value",
    "number": 123,
    "nested": {
      "key": "value"
    }
  }
}
```

### 3. Mise à Jour du Statut de Contrôle
**Endpoint:** `POST /api/external/update-control-status/`

Met à jour le statut de contrôle pour les détections d'une parcelle spécifique.

**Requête:**
```json
{
  "insee_code": "34172",
  "parcel_code": "AB1234",
  "control_status": "CONTROLLED_FIELD"
}
```

#### Paramètres de la Requête

- **`insee_code`** (string, requis)
  - Code INSEE de la commune
  - Exemple: "34172" (Montpellier)

- **`parcel_code`** (string, requis)
  - Code cadastral de la parcelle
  - Format: 1-2 lettres majuscules + 1-4 chiffres
  - Exemples: "B39", "AB1234", "C1"

- **`control_status`** (string, requis)
  - Doit être l'une des valeurs de l'enum `DetectionControlStatus`
  - Voir les valeurs valides ci-dessous

#### Valeurs Valides pour control_status

| Valeur | Description |
|--------|-------------|
| `NOT_CONTROLLED` | Non contrôlé |
| `PRIOR_LETTER_SENT` | Courrier préalable envoyé |
| `CONTROLLED_FIELD` | Contrôlé terrain |
| `OFFICIAL_REPORT_DRAWN_UP` | PV dressé |
| `ADMINISTRATIVE_CONSTRAINT` | Astreinte Administrative |
| `OBSERVARTION_REPORT_REDACTED` | Rapport de constatations rédigé |
| `REHABILITATED` | Remis en état |

**Note:** La faute de frappe dans `OBSERVARTION_REPORT_REDACTED` existe dans le code source et doit être utilisée telle quelle.

#### Exemples de Réponses

**Succès (200 OK):**
```json
{}
```

**Erreur de Validation - Code Parcelle Invalide (400 Bad Request):**
```json
{
  "parcel_code": [
    "Code parcelle invalide. Format attendu: 1-2 lettres suivi de 1-4 chiffres (exemples : 'B39', 'AB1234')"
  ]
}
```

**Erreur de Validation - Champs Manquants (400 Bad Request):**
```json
{
  "parcel_code": [
    "This field is required."
  ],
  "control_status": [
    "This field is required."
  ]
}
```

**Erreur de Validation - Statut de Contrôle Invalide (400 Bad Request):**
```json
{
  "control_status": [
    "\"INVALID_STATUS\" is not a valid choice."
  ]
}
```

**Erreur d'Authentification (403 Forbidden):**
```json
{
  "detail": "Invalid API key"
}
```
orrespondre au modèle : 1-2 lettres + 1-4 chiffres

## Dépannage

### 403 Forbidden - Invalid API Key
- Vérifiez que votre clé API est correcte
- Vérifiez si la clé API a expiré
- Générez une nouvelle clé API si nécessaire

### 400 Bad Request - Invalid Choice
- Assurez-vous d'utiliser exactement l'une des valeurs valides de statut de contrôle listées ci-dessus
- Les valeurs sont sensibles à la casse (utilisez MAJUSCULES avec underscores)

### 400 Bad Request - Invalid Parcel Code
- Le code parcelle doit être composé de 1-2 lettres majuscules suivies de 1-4 chiffres
- Exemples valides: "B39", "AB1234", "C1"
- Exemples invalides: "abc123", "123", "ABCD1234"
