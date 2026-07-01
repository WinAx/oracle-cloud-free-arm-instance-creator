# Oracle Always Free ARM Instance — Auto Creator

A small Python utility that repeatedly tries to create an Oracle Cloud Infrastructure
Compute instance across multiple Availability Domains.

It was built for the common case where an allowed shape is temporarily unavailable
and the OCI API returns capacity errors. The script does not bypass quotas, service
limits, billing rules, or OCI policies. It simply sends normal `oci compute instance
launch` requests with the official OCI CLI and stops as soon as one request succeeds.

## Features

- Uses the official OCI CLI and API key authentication.
- Reads all settings from a local `config.json` file.
- Retries instance creation across multiple Availability Domains.
- Stops immediately after a successful launch.
- Adds jitter between attempts to avoid a perfectly fixed request pattern.
- Applies a longer exponential delay when OCI returns rate-limit responses.
- Stops on non-retryable service-limit, quota, permission, and invalid-parameter errors.
- Has a dry-run mode that prints the exact `oci compute instance launch` commands.
- Has no third-party Python package dependencies.

## Requirements

- Python 3.10 or newer.
- Oracle Cloud Infrastructure CLI.
- An OCI API key configured for the target tenancy.
- A VCN subnet where the instance should be created.
- An SSH public key file for instance access.
- OCI permissions to launch Compute instances in the target compartment.

## Current Always Free A1 Allocation

Oracle currently documents the Always Free Ampere A1 allocation as a total of
2 OCPUs and 12 GB of memory per tenancy in its home region. Oracle can change
service limits, so verify the values shown under Limits, Quotas and Usage before
choosing a larger configuration.

https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

## Install OCI CLI

Follow Oracle's official OCI CLI installation guide:

https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm

### Linux

Oracle provides an installer script for Linux and Unix-like systems:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

Restart your shell or add the OCI CLI path printed by the installer to your `PATH`.

### macOS

Use the Oracle installer script:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

If you use Homebrew Python, make sure the `oci` command is available in the same
shell where you run this project.

### Windows

Install the OCI CLI with Oracle's Windows installer instructions:

https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/cliinstall.htm#InstallingCLI__windows

Then run this project from PowerShell, Command Prompt, or Windows Terminal.

## Configure OCI CLI

Run:

```bash
oci setup config
```

The setup command creates an OCI config file, usually at:

```text
~/.oci/config
```

Use the same profile name in `config.json`. The default profile name is `DEFAULT`.

Verify that authentication works:

```bash
oci iam region list --auth api_key --profile DEFAULT
```

## Prepare Project Configuration

Clone or copy this project, then create your local config:

```bash
cp config.example.json config.json
```

Edit `config.json` and fill in your own values:

```json
{
  "profile": "DEFAULT",
  "compartment_id": "ocid1.tenancy.oc1..example",
  "image_id": "ocid1.image.oc1.<region>.example",
  "subnet_id": "ocid1.subnet.oc1.<region>.example",
  "ssh_public_key_file": "/path/to/id_rsa.pub",
  "display_name": "a1-flex",
  "shape": "VM.Standard.A1.Flex",
  "ocpus": 2,
  "memory_gb": 12,
  "boot_volume_gb": 50,
  "availability_domains": [
    "example:REGION-AD-1",
    "example:REGION-AD-2",
    "example:REGION-AD-3"
  ]
}
```

`config.json` is intentionally ignored by git because it contains tenancy-specific
resource identifiers.

## Find Required OCI Values

Set your compartment OCID first:

```bash
export COMPARTMENT_ID="ocid1.tenancy.oc1..example"
```

List Availability Domains:

```bash
oci iam availability-domain list \
  --compartment-id "$COMPARTMENT_ID" \
  --auth api_key \
  --profile DEFAULT
```

List images:

```bash
oci compute image list \
  --compartment-id "$COMPARTMENT_ID" \
  --shape VM.Standard.A1.Flex \
  --all \
  --auth api_key \
  --profile DEFAULT
```

List subnets:

```bash
oci network subnet list \
  --compartment-id "$COMPARTMENT_ID" \
  --all \
  --auth api_key \
  --profile DEFAULT
```

## Usage

Make the script executable on Linux or macOS:

```bash
chmod +x a1_hammer.py
```

Run a dry run:

```bash
./a1_hammer.py --dry-run --once
```

Run continuously:

```bash
./a1_hammer.py
```

Run with explicit timing:

```bash
./a1_hammer.py --interval 30 --jitter 10
```

Run in the background on Linux:

```bash
nohup ./a1_hammer.py \
  --interval 30 \
  --jitter 10 \
  --log-file ./a1_hammer.log \
  > ./a1_hammer.out 2>&1 &
```

Watch logs:

```bash
tail -f ./a1_hammer.log ./a1_hammer.out
```

On Windows PowerShell:

```powershell
python .\a1_hammer.py --dry-run --once
python .\a1_hammer.py --interval 30 --jitter 10
```

## Command Options

```text
--config PATH              Path to config.json.
--log-file PATH            Path to the log file.
--interval SECONDS         Sleep after each failed launch request.
--jitter SECONDS           Random extra sleep after each failed request.
--throttle-sleep SECONDS   Base sleep after rate-limit responses.
--max-throttle-sleep SEC   Maximum sleep after repeated rate-limit responses.
--max-attempts N           Stop after N launch attempts.
--once                     Try each Availability Domain once, then exit.
--shuffle                  Shuffle Availability Domain order on startup.
--dry-run                  Print launch commands without creating an instance.
```

## Notes on Request Timing

OCI does not publish a single universal request interval for instance launch
attempts. If the API returns rate-limit errors such as `Too many requests`, the
script increases the delay before continuing.

Start conservatively, for example:

```bash
./a1_hammer.py --interval 30 --jitter 10
```

Use shorter intervals only if they are appropriate for your tenancy and workload.

## How Long Will It Take

There is no way to predict when Oracle will free up capacity. Based on community
reports it can take anywhere from a few hours to several weeks depending on the
region and time of day. Capacity varies by region and can change without notice.

To improve your chances:

- Use a Pay As You Go account instead of a free trial account.
- Keep the script running continuously.
- All three Availability Domains are tried automatically.

## Tests

Run the standard-library unit tests from the repository root:

```bash
python -m unittest discover -s tests -v
```

## License

This project is licensed under the [MIT License](LICENSE).
