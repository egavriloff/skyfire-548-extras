.PHONY: module-build module-build-image module-build-list module-build-download module-build-update module-build-status module-build-clean

module-build:
	@if [ -n "$(MODULE)" ]; then \
		bash .ci/module-build/build.sh "$(MODULE)"; \
	else \
		bash .ci/module-build/build.sh all; \
	fi

module-build-image:
	@bash .ci/module-build/build.sh image

module-build-list:
	@bash .ci/module-build/build.sh list

module-build-download:
	@bash .ci/module-build/build.sh download

module-build-update:
	@bash .ci/module-build/build.sh update

module-build-status:
	@bash .ci/module-build/build.sh status

module-build-clean:
	@bash .ci/module-build/build.sh clean
